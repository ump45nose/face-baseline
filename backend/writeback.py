import ctypes
import json
import os
import shutil
import subprocess
from pathlib import Path

from .images import decode, fingerprint
from .store import now


CONFIG = Path(__file__).with_name('face-baseline-xmp.config')
PREFIX = '基线__'


class Writeback:
    def __init__(self, store):
        self.store = store

    def record(self, db, person, photo, kind, payload):
        db.execute('INSERT INTO operations(person_id,photo_id,kind,payload,created) VALUES(?,?,?,?,?)',
                   (person, photo, kind, json.dumps(payload, ensure_ascii=False), now()))
        if photo:
            db.execute("UPDATE photos SET writeback='failed' WHERE id=?", (photo,))

    def repair(self, person=None):
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM operations WHERE status='pending'" +
                              (' AND person_id=?' if person else '') + ' ORDER BY id',
                              (person,) if person else ()).fetchall()
        blocked = set()
        for row in rows:
            if row['person_id'] in blocked:
                continue
            try:
                self.apply(row)
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                with self.store.connect() as db:
                    db.execute('UPDATE operations SET error=? WHERE id=?', (str(exc), row['id']))
                blocked.add(row['person_id'])
        return blocked

    def apply(self, op):
        payload = json.loads(op['payload'])
        with self.store.connect() as db:
            photo = db.execute('SELECT * FROM photos WHERE id=?', (op['photo_id'],)).fetchone()
        path = Path(photo['path']) if photo else None
        kind = op['kind']
        if kind == 'rename':
            src, dst = Path(payload['source']), Path(payload['target'])
            if src.exists():
                if decode(src)[1] != payload['hash']:
                    raise RuntimeError('改名前图像已变化，等待重新扫描')
                # Atomic Linux RENAME_NOREPLACE: never overwrite an unrelated file.
                libc = ctypes.CDLL(None, use_errno=True)
                if libc.renameat2(-100, os.fsencode(src), -100, os.fsencode(dst), 1) != 0:
                    err = ctypes.get_errno()
                    raise OSError(err, os.strerror(err), str(dst))
            elif not dst.exists() or decode(dst)[1] != payload['hash'] or fingerprint(dst)[:2] != tuple(payload['identity']):
                raise RuntimeError('改名恢复时源文件与目标文件均不匹配')
            path = dst
            self.update_stat(photo['id'], path)
            with self.store.connect() as db:
                db.execute('UPDATE photos SET named_baseline=? WHERE id=?', (int(payload['baseline']), photo['id']))
        elif kind == 'snapshot':
            dst = self.store.data / payload['destination']
            if not dst.exists():
                before = fingerprint(path)
                if decode(path)[1] != payload['hash']:
                    raise RuntimeError('快照源图像已变化，等待重新扫描')
                dst.parent.mkdir(parents=True, exist_ok=True)
                temp = dst.with_suffix('.tmp')
                shutil.copy2(path, temp)
                if fingerprint(path) != before or decode(temp)[1] != payload['hash']:
                    temp.unlink()
                    raise RuntimeError('保存快照期间文件变化')
                temp.replace(dst)
            elif decode(dst)[1] != payload['hash']:
                raise RuntimeError('历史快照内容不匹配')
        elif kind == 'metadata':
            before = fingerprint(path)
            if decode(path)[1] != payload['hash']:
                raise RuntimeError('元数据写回前图像已变化，等待重新扫描')
            temp = path.with_name('.face-baseline-' + photo['id'] + path.suffix)
            shutil.copy2(path, temp)
            try:
                args = ['exiftool', '-config', str(CONFIG), '-overwrite_original', '-P']
                args += [f'-XMP-fb:{key}={value}' for key, value in payload['fields'].items()]
                result = subprocess.run(args + [str(temp)], capture_output=True, text=True, check=True)
                if '1 image files updated' not in result.stdout:
                    raise RuntimeError(result.stderr.strip() or result.stdout.strip())
                if decode(temp)[1] != payload['hash']:
                    raise RuntimeError('ExifTool 改变了图像内容，未替换原文件')
                if fingerprint(path) != before:
                    raise RuntimeError('元数据写回期间原文件变化，未替换原文件')
                # Keep mtime; database records the new inode/size after replacing.
                temp.replace(path)
                self.update_stat(photo['id'], path)
            finally:
                temp.unlink(missing_ok=True)
            with self.store.connect() as db:
                db.execute('UPDATE photos SET metadata=? WHERE id=?',
                           (json.dumps(payload['fields'], ensure_ascii=False, sort_keys=True), photo['id']))
        with self.store.connect() as db:
            db.execute("UPDATE operations SET status='done', error=NULL WHERE id=?", (op['id'],))
            if photo and not db.execute("SELECT 1 FROM operations WHERE photo_id=? AND status='pending' AND id<>?",
                                        (photo['id'], op['id'])).fetchone():
                db.execute("UPDATE photos SET writeback='ok' WHERE id=?", (photo['id'],))

    def update_stat(self, photo_id, path):
        dev, inode, size, mtime = fingerprint(path)
        with self.store.connect() as db:
            db.execute('UPDATE photos SET path=?,device=?,inode=?,size=?,mtime=? WHERE id=?',
                       (str(path), dev, inode, size, mtime, photo_id))

    def target_name(self, path, original, baseline, photo_id):
        base = original
        if baseline:
            while base.startswith(PREFIX):
                base = base[len(PREFIX):]
        target = path.with_name((PREFIX if baseline else '') + base)
        if target != path and target.exists():
            name = Path(original)
            target = path.with_name((PREFIX if baseline else '') + name.stem + '__' + photo_id + name.suffix)
        return target
