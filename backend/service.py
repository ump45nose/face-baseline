import json
import threading
import uuid
from pathlib import Path

from PIL import UnidentifiedImageError

from .images import EXTENSIONS, decode, fingerprint, thumbnail
from .store import now
from .quality import POLICY_VERSION, assess
from .engine import engine_for
from .writeback import Writeback


def uid():
    return uuid.uuid4().hex


class BusyError(RuntimeError):
    pass


class ScanCancelled(Exception):
    pass


class BaselineService:
    def __init__(self, store, engine, stable_seconds=10, browse_roots=None):
        self.store, self.engine = store, engine
        self.engine_factory = lambda model: engine_for(model, store)
        self.stable_seconds = stable_seconds
        self.mutex = threading.Lock()
        self.jobs_mutex = threading.RLock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.cancel_scan = threading.Event()
        self.writeback = Writeback(store)
        self.thread = None
        self.browse_roots = [Path(p).resolve() for p in (browse_roots or ['/vol3/1000/Picture/YY/人物'])]

    def discover(self):
        directories = [Path(p) for p in self.store.settings()['folders']]
        with self.store.connect() as db:
            for path in directories:
                db.execute('INSERT OR IGNORE INTO people(id,directory,name) VALUES(?,?,?)',
                           (uid(), str(path), path.name))
            return [dict(db.execute('SELECT * FROM people WHERE directory=?', (str(p),)).fetchone()) for p in directories]

    def start(self):
        # Scanning is manual: preserve interrupted results without restarting a job.
        for job in self.store.jobs():
            if job['status'] in ('running', 'queued'):
                job.update(status='cancelled' if job.get('cancelRequested') else 'failed', finishedAt=now())
                job['log'].append({'level': 'warn', 'text': '服务重启，扫描已停止，已有结果保留；请手动扫描继续'})
                self.store.job(job)
        self.thread = threading.Thread(target=self.worker, name='scan-worker', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.cancel_scan.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=5)

    def submit(self, scope='all'):
        with self.jobs_mutex:
            selected = self.discover()
            if not selected:
                raise ValueError('请先选择至少一个图库目录')
            person = next((p for p in selected if p['id'] == scope), None)
            if scope != 'all' and not person:
                raise ValueError('该目录未选入图库')
            active = [j for j in self.store.jobs() if j['status'] in ('queued', 'running')]
            if any(j.get('cancelRequested') for j in active):
                raise BusyError('正在停止扫描，完成当前照片处理后可重新开始')
            for job in active:
                if job['scope'] == 'all' or job['scope'] == scope or job['status'] == 'queued':
                    if job['status'] == 'queued' and job['scope'] != scope:
                        job.update(scope='all', scopeLabel='所选图库')
                    job['merged'] += 1
                    self.store.job(job)
                    return {'merged': True, 'job': job}
            job = dict(id=uid(), scope=scope, scopeLabel='所选图库' if scope == 'all' else person['name'],
                       trigger='manual', status='queued', processed=0, total=0, startedAt=now(),
                       finishedAt=None, merged=0, scored=0, fileProcessed=0, fileTotal=0, cancelRequested=False,
                       model=self.store.settings()['model'], log=[])
            self.store.job(job)
            self.wake.set()
            return {'merged': False, 'job': job}

    def save_job(self, job):
        with self.jobs_mutex:
            current = next(j for j in self.store.jobs() if j['id'] == job['id'])
            job['merged'] = current['merged']
            job['cancelRequested'] = current.get('cancelRequested', False)
            self.store.job(job)

    def stop_scans(self):
        with self.jobs_mutex:
            jobs = [j for j in self.store.jobs() if j['status'] in ('queued', 'running')]
            for job in jobs:
                job['cancelRequested'] = True
                if job['status'] == 'queued':
                    job.update(status='cancelled', finishedAt=now())
                    job['log'].append({'level': 'info', 'text': '已取消排队，未开始扫描'})
                self.store.job(job)
            if any(j['status'] == 'running' for j in jobs):
                self.cancel_scan.set()
            return {'jobs': jobs}

    def check_cancel(self):
        if self.stop.is_set():
            raise RuntimeError('扫描已中断，已有结果保留')
        if self.cancel_scan.is_set():
            raise ScanCancelled()

    def worker(self):
        while not self.stop.is_set():
            self.wake.wait()
            self.wake.clear()
            while not self.stop.is_set():
                with self.jobs_mutex:
                    job = next((j for j in reversed(self.store.jobs()) if j['status'] == 'queued'), None)
                    if not job:
                        break
                    self.cancel_scan.clear()
                    job['status'] = 'running'
                    self.store.job(job)
                with self.mutex:
                    try:
                        self.scan(job)
                    except ScanCancelled:
                        job['status'] = 'cancelled'
                    except Exception as exc:
                        job['status'] = 'failed'
                        job['log'].append({'level': 'error', 'text': str(exc)})
                    with self.jobs_mutex:
                        self.save_job(job)
                        if job['cancelRequested'] and job['status'] in ('done', 'partial'):
                            job['status'] = 'cancelled'
                        if job['status'] == 'cancelled':
                            job['log'].insert(0, {'level': 'info', 'text': f'扫描已停止，保留已处理的 {job["fileProcessed"]} 张照片与评分；下次手动扫描跳过未变化照片'})
                        job['finishedAt'] = now()
                        self.save_job(job)

    def scan(self, job):
        people = self.discover()
        if job['scope'] != 'all':
            people = [p for p in people if p['id'] == job['scope']]
        job['total'] = len(people)
        self.save_job(job)
        # Recover file writes before enumeration, including rename interrupted after fs commit.
        for person in people:
            self.check_cancel()
            self.writeback.repair(person['id'])
        first, paths = {}, {}
        for person in people:
            self.check_cancel()
            directory = Path(person['directory'])
            if not directory.is_dir():
                raise ValueError(f'图库目录不可用：{directory}')
            paths[person['id']] = []
            for path in sorted(Path(person['directory']).rglob('*')):
                self.check_cancel()
                if path.suffix.lower() not in EXTENSIONS or path.is_symlink() or any(part.startswith('.') for part in path.relative_to(person['directory']).parts):
                    continue
                if not path.is_file():
                    continue
                paths[person['id']].append(path)
                try:
                    first[str(path)] = fingerprint(path)
                except FileNotFoundError:
                    pass
        job['fileProcessed'] = 0
        job['fileTotal'] = sum(len(items) for items in paths.values())
        self.save_job(job)
        if first:
            self.cancel_scan.wait(self.stable_seconds)
        self.check_cancel()
        partial = False
        for person in people:
            seen = set()
            affected = False
            try:
                for path in paths[person['id']]:
                    self.check_cancel()
                    try:
                        st = fingerprint(path)
                    except FileNotFoundError:
                        continue
                    stable = first.get(str(path)) == st
                    photo, scored, warning, changed = self.process(person, path, st, stable, seen)
                    affected = affected or changed
                    seen.add(photo)
                    job['scored'] += scored
                    job['fileProcessed'] += 1
                    if warning:
                        partial = True
                        job['log'].append({'level': 'warn', 'text': f'{person["name"]}：{path.name} · {warning}'})
                    if job['fileProcessed'] % 5 == 0:
                        self.save_job(job)
                self.check_cancel()
            except ScanCancelled:
                # Never mark unvisited photos missing during a partial scan.
                if affected:
                    self.reconcile(person['id'], '扫描停止，保留已完成的候选与基线更新')
                    self.writeback.repair(person['id'])
                raise
            with self.store.connect() as db:
                ids = [r['id'] for r in db.execute('SELECT id FROM photos WHERE person_id=? AND present=1', (person['id'],))]
                affected = affected or bool(set(ids) - seen)
                for photo_id in set(ids) - seen:
                    db.execute('UPDATE photos SET present=0 WHERE id=?', (photo_id,))
                db.execute('UPDATE people SET last_scan=? WHERE id=?', (now(), person['id']))
            settings = self.store.settings()
            rules = self.rules(settings)
            selection_incomplete = (person['locked_id'] and person['baseline_id'] != person['locked_id']) or (not person['locked_id'] and person['mode'] == 'locked')
            if affected or person['rules'] != rules or selection_incomplete:
                self.reconcile(person['id'], '扫描后更新候选与基线')
            failed = self.writeback.repair(person['id'])
            if failed:
                partial = True
                job['log'].append({'level': 'warn', 'text': f'{person["name"]}：文件写回待修复，下次扫描继续处理'})
            job['processed'] += 1
            self.save_job(job)
        job['status'] = 'partial' if partial else 'done'
        job['log'].insert(0, {'level': 'info', 'text': f'扫描 {job["total"]} 位人物，本次评分 {job["scored"]} 张；未变化图像已跳过'})

    def process(self, person, path, st, stable, seen):
        ownership_changed = False
        with self.store.connect() as db:
            previous = db.execute('SELECT * FROM photos WHERE path=?', (str(path),)).fetchone()
            if not previous:
                matches = db.execute('SELECT * FROM photos WHERE person_id=? AND device=? AND inode=?',
                                     (person['id'], st[0], st[1])).fetchall()
                previous = next((p for p in matches if p['id'] not in seen and not Path(p['path']).exists()), None)
            photo_id = previous['id'] if previous else uid()
            if previous:
                ownership_changed = previous['person_id'] != person['id']
                if ownership_changed:
                    db.execute("UPDATE photos SET person_id=?,rank=NULL,metadata=NULL WHERE id=?", (person['id'], photo_id))
                    db.execute("UPDATE operations SET status='superseded',error='照片已归入另一个所选目录' WHERE photo_id=? AND kind IN ('rename','metadata') AND status='pending'", (photo_id,))
                db.execute('UPDATE photos SET path=?,present=1 WHERE id=?', (str(path), photo_id))
                if ownership_changed or previous['path'] != str(path):
                    db.execute('UPDATE people SET rules=NULL WHERE id=?', (person['id'],))
                if previous['path'] != str(path) and not path.name.startswith('基线__'):
                    db.execute('UPDATE photos SET original_name=? WHERE id=?', (path.name, photo_id))
            else:
                db.execute('INSERT INTO photos(id,person_id,path,original_name,status,added) VALUES(?,?,?,?,?,?)',
                           (photo_id, person['id'], str(path), path.name, 'incomplete', now()))
        if not stable:
            with self.store.connect() as db:
                db.execute("UPDATE photos SET status='incomplete',score=NULL,error=? WHERE id=?", ('文件大小或修改时间仍在变化', photo_id))
                db.execute('UPDATE people SET rules=NULL WHERE id=?', (person['id'],))
            return photo_id, 0, '文件未写完，下次重试', ownership_changed or not previous or previous['status'] != 'incomplete'
        if previous and previous['engine'] == self.engine.version and tuple(previous[k] for k in ('device', 'inode', 'size', 'mtime')) == st and previous['status'] not in ('incomplete', 'score_failed'):
            return photo_id, 0, None, ownership_changed or previous['path'] != str(path)
        result, scored, digest = None, 0, None
        try:
            image, digest = decode(path)
            with self.store.connect() as db:
                cached = db.execute('SELECT result FROM scores WHERE hash=? AND engine=?', (digest, self.engine.version)).fetchone()
            if cached:
                result = json.loads(cached[0])
            else:
                result = self.engine.score(image)
                scored = 1
            if fingerprint(path) != st:
                raise RuntimeError('处理期间文件变化')
            thumbnail(image, self.store.data / 'thumbnails' / (photo_id + '.jpg'))
            if fingerprint(path) != st:
                raise RuntimeError('处理期间文件变化')
            with self.store.connect() as db:
                if result['status'] != 'score_failed':
                    db.execute('INSERT OR REPLACE INTO scores VALUES(?,?,?)', (digest, self.engine.version, json.dumps(result)))
        except (UnidentifiedImageError, OSError) as exc:
            result = dict(status='decode_failed', score=None, metrics={}, error=str(exc))
        except RuntimeError as exc:
            result = dict(status='incomplete', score=None, metrics={}, error=str(exc))
            digest = None
        with self.store.connect() as db:
            # Results from a changed file are never accepted. Its prior history remains immutable.
            if previous and previous['hash'] != digest:
                pending = db.execute("SELECT * FROM operations WHERE photo_id=? AND status='pending'", (photo_id,)).fetchall()
                for op in pending:
                    db.execute("UPDATE operations SET status='superseded',error='图像已变化，操作作废' WHERE id=?", (op['id'],))
                db.execute("UPDATE photos SET metadata=NULL,writeback='none' WHERE id=?", (photo_id,))
            db.execute('UPDATE photos SET device=?,inode=?,size=?,mtime=?,hash=?,status=?,score=?,metrics=?,engine=?,error=?,present=1 WHERE id=?',
                       (*st, digest, result['status'], result['score'], json.dumps(result['metrics']), self.engine.version, result.get('error'), photo_id))
            changed = ownership_changed or not previous or previous['engine'] != self.engine.version or previous['hash'] != digest or previous['status'] != result['status'] or previous['path'] != str(path)
            if changed:
                db.execute('UPDATE people SET rules=NULL WHERE id=?', (person['id'],))
        warning = result.get('error') if result['status'] in ('incomplete', 'score_failed', 'decode_failed') else None
        return photo_id, scored, warning, changed

    def rules(self, settings):
        return json.dumps([settings['k'], settings['threshold'], self.engine.version, POLICY_VERSION])

    def upgrade_rules(self):
        settings = self.store.settings()
        self.restore_cached_scores()
        for person in self.discover():
            if person['rules'] != self.rules(settings):
                self.writeback.repair(person['id'])
                self.reconcile(person['id'], '基线规则升级，重新核对可靠性')
                self.writeback.repair(person['id'])

    def restore_cached_scores(self):
        # A model switch can reuse a prior result only for an unchanged file.
        for person in self.discover():
            with self.store.connect() as db:
                photos = db.execute('SELECT * FROM photos WHERE person_id=? AND present=1 AND engine!=?', (person['id'], self.engine.version)).fetchall()
                for photo in photos:
                    path = Path(photo['path'])
                    if not path.is_file() or fingerprint(path) != tuple(photo[k] for k in ('device', 'inode', 'size', 'mtime')):
                        continue
                    cached = db.execute('SELECT result FROM scores WHERE hash=? AND engine=?', (photo['hash'], self.engine.version)).fetchone()
                    if cached:
                        result = json.loads(cached[0])
                        db.execute('UPDATE photos SET status=?,score=?,metrics=?,engine=?,error=? WHERE id=?',
                                   (result['status'], result['score'], json.dumps(result['metrics']), self.engine.version, result.get('error'), photo['id']))
                        db.execute('UPDATE people SET rules=NULL WHERE id=?', (person['id'],))

    def reconcile(self, person_id, reason):
        settings = self.store.settings()
        with self.store.connect() as db:
            person = db.execute('SELECT * FROM people WHERE id=?', (person_id,)).fetchone()
            photos = db.execute('SELECT * FROM photos WHERE person_id=? AND present=1 ORDER BY added,id', (person_id,)).fetchall()
            quality = {p['id']: assess(p, settings['threshold'], self.engine.version) for p in photos}
            scored = sorted((p for p in photos if quality[p['id']]['eligible']),
                            key=lambda p: (not quality[p['id']]['qualified'], -p['score'], p['id'] != person['locked_id'], p['added'], p['id']))
            unique, hashes = [], set()
            for photo in scored:
                if photo['hash'] not in hashes:
                    unique.append(photo)
                    hashes.add(photo['hash'])
            top = unique[:settings['k']]
            ranks = {p['id']: i + 1 for i, p in enumerate(top)}
            locked = next((p for p in scored if p['id'] == person['locked_id']), None)
            if not locked:
                locked = next((p for p in photos if p['id'] == person['locked_id'] and p['status'] == 'ok'
                               and p['engine'] != self.engine.version and json.loads(p['metrics'] or '{}').get('FaceValidation', {}).get('matched')
                               and p['engine'].startswith('FaceQnet-') != self.engine.version.startswith('FaceQnet-')
                               and (self.engine.version.endswith(p['engine']) or p['engine'].endswith(self.engine.version))
                               and Path(p['path']).is_file() and fingerprint(Path(p['path'])) == tuple(p[k] for k in ('device','inode','size','mtime'))), None)
            baseline = locked or next((p for p in top if quality[p['id']]['qualified']), None)
            # A missing/invalid locked file does not silently select a different reference.
            if person['locked_id'] and not locked:
                baseline = None
            mode = 'locked' if person['locked_id'] else 'auto' if baseline else 'missing'
            bid, bhash = (baseline['id'], baseline['hash']) if baseline else (None, None)
            changed = (bid, bhash, mode) != (person['baseline_id'], person['baseline_hash'], person['mode'])
            if changed:
                version = person['version'] + 1
                snapshot = f'snapshots/{person_id}/v{version}{Path(baseline["original_name"]).suffix}' if baseline else None
                if baseline:
                    self.writeback.record(db, person_id, bid, 'snapshot', {'destination': snapshot, 'hash': bhash})
                db.execute('INSERT INTO history(person_id,version,at,reason,mode,photo_id,hash,file_name,score,snapshot,engine) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (person_id, version, now(), reason, mode, bid, bhash,
                            '基线__' + baseline['original_name'] if baseline else None,
                            baseline['score'] if baseline else None, snapshot, baseline['engine'] if baseline else self.engine.version))
                db.execute('UPDATE people SET baseline_id=?,baseline_hash=?,mode=?,version=? WHERE id=?', (bid, bhash, mode, version, person_id))
            # Restore old baselines before naming a new one; every step is journaled.
            ordered = sorted(photos, key=lambda p: p['id'] == bid)
            pending_rename = {r['photo_id'] for r in db.execute("SELECT photo_id FROM operations WHERE kind='rename' AND status='pending'")}
            for photo in ordered:
                path = Path(photo['path'])
                original = photo['original_name']
                prior_meta = json.loads(photo['metadata']) if photo['metadata'] else {}
                was_baseline = photo['named_baseline'] or prior_meta.get('CurrentBaseline') == 'True' or photo['id'] == person['baseline_id']
                if (photo['id'] == bid or was_baseline) and photo['hash'] and photo['id'] not in pending_rename:
                    target = self.writeback.target_name(path, original, photo['id'] == bid, photo['id'])
                    if target != path:
                        self.writeback.record(db, person_id, photo['id'], 'rename',
                                              {'source': str(path), 'target': str(target), 'hash': photo['hash'],
                                               'identity': [photo['device'], photo['inode']], 'baseline': photo['id'] == bid})
            for photo in ordered:
                original = photo['original_name']
                rank = ranks.get(photo['id'])
                db.execute('UPDATE photos SET rank=? WHERE id=?', (rank, photo['id']))
                active = rank is not None or photo['id'] == person['locked_id']
                if not active and not photo['metadata']:
                    continue
                fields = dict(PhotoID=photo['id'], PersonID=person_id, OriginalName=original,
                              Score=str(photo['score']) if photo['score'] is not None else '',
                              Metrics=photo['metrics'] or '{}', EngineVersion=photo['engine'] or '',
                              ScoringModel='faceqnet' if (photo['engine'] or '').startswith('FaceQnet-') else 'ofiq',
                              Qualified=str(quality[photo['id']]['qualified']),
                              CandidateRank=str(rank) if rank else '',
                              CurrentBaseline=str(photo['id'] == bid) if active else '',
                              Locked=str(photo['id'] == person['locked_id']) if active else '')
                serialized = json.dumps(fields, ensure_ascii=False, sort_keys=True)
                pending_meta = db.execute("SELECT payload FROM operations WHERE photo_id=? AND kind='metadata' AND status='pending' ORDER BY id DESC LIMIT 1", (photo['id'],)).fetchone()
                pending_fields = json.loads(pending_meta[0])['fields'] if pending_meta else None
                if photo['hash'] and serialized != photo['metadata'] and fields != pending_fields:
                    self.writeback.record(db, person_id, photo['id'], 'metadata', {'hash': photo['hash'], 'fields': fields})
            db.execute('UPDATE people SET rules=? WHERE id=?', (self.rules(settings), person_id))

    def mutate(self, fn):
        if not self.mutex.acquire(blocking=False):
            raise BusyError('扫描或文件写回进行中，完成后再操作')
        try:
            if any(j['status'] in ('queued', 'running') for j in self.store.jobs()):
                raise BusyError('扫描已排队，完成后再操作')
            return fn()
        finally:
            self.mutex.release()

    def lock(self, person_id, photo_id):
        def apply():
            self.writeback.repair(person_id)
            with self.store.connect() as db:
                photo = db.execute('SELECT * FROM photos WHERE id=? AND person_id=? AND present=1', (photo_id, person_id)).fetchone()
                if not photo or not assess(photo, self.store.settings()['threshold'], self.engine.version)['eligible']:
                    raise ValueError('只能选择通过新版单人复核并成功评分的照片')
                if not Path(photo['path']).is_file() or decode(Path(photo['path']))[1] != photo['hash']:
                    raise ValueError('照片已变化或不可用，请重新扫描后选择')
                db.execute('UPDATE people SET locked_id=? WHERE id=?', (photo_id, person_id))
            self.reconcile(person_id, '手动设为基线并锁定')
            self.writeback.repair(person_id)
        self.mutate(apply)

    def unlock(self, person_id):
        def apply():
            self.writeback.repair(person_id)
            with self.store.connect() as db:
                if not db.execute('SELECT 1 FROM people WHERE id=?', (person_id,)).fetchone():
                    raise ValueError('找不到该人物')
                db.execute('UPDATE people SET locked_id=NULL WHERE id=?', (person_id,))
            self.reconcile(person_id, '取消锁定，恢复自动选择')
            self.writeback.repair(person_id)
        self.mutate(apply)

    def settings(self, settings):
        def apply():
            folders = []
            previous = self.store.settings()
            settings['model'] = settings.get('model', previous['model'])
            settings['thresholds'] = {**previous['thresholds'], settings['model']: settings['threshold']}
            for value in settings['folders']:
                path = self.folder_path(value)
                if any(path == other or path.is_relative_to(other) or other.is_relative_to(path) for other in folders):
                    raise ValueError('请勿重复选择同一目录或相互包含的父子目录')
                if str(path) not in previous['folders']:
                    if not path.is_dir():
                        raise ValueError(f'图库目录不可用：{path}')
                    list(path.iterdir())
                folders.append(path)
            settings['folders'] = [str(p) for p in folders]
            if previous['model'] != settings['model']:
                self.engine.close()
                self.engine = self.engine_factory(settings['model'])
            with self.store.connect() as db:
                db.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(settings, ensure_ascii=False),))
            people = self.discover()
            if previous['model'] != settings['model']:
                self.restore_cached_scores()
            if (previous['k'], previous['threshold'], previous['model']) != (settings['k'], settings['threshold'], settings['model']):
                for person in people:
                    self.reconcile(person['id'], '设置变更后重新计算')
                    self.writeback.repair(person['id'])
        self.mutate(apply)

    def folder_path(self, value):
        path = Path(value)
        if not path.is_absolute():
            raise ValueError('请选择绝对目录路径')
        path = path.resolve()
        if not any(path.is_relative_to(root) for root in self.browse_roots):
            raise ValueError('该目录未挂载到服务，请选择文件夹浏览器中的目录')
        return path

    def browse(self, value=None):
        if value is None:
            return {'path': None, 'parent': None, 'directories': [
                {'path': str(p), 'name': str(p), 'available': p.is_dir()} for p in self.browse_roots]}
        path = self.folder_path(value)
        try:
            directories = [p for p in path.iterdir() if p.is_dir() and not p.name.startswith('.') and not p.is_symlink()]
        except OSError as exc:
            raise ValueError(f'无法打开目录：{path}（{exc.strerror}）') from exc
        parent = str(path.parent) if any(path.parent.is_relative_to(root) for root in self.browse_roots) else None
        return {'path': str(path), 'parent': parent, 'directories': [
            {'path': str(p), 'name': p.name, 'available': True} for p in sorted(directories, key=lambda p: p.name)]}
