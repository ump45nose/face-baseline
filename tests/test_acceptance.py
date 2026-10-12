import json
import shutil
import subprocess
import struct
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from backend.app import create_app, serialize_person
from backend.images import decode, fingerprint
from backend.service import BaselineService
from backend.store import Store, now
from backend.quality import MINIMUMS, assess


class Engine:
    version = 'acceptance-fixture'
    def __init__(self):
        self.calls = 0
        self.change = None
    def score(self, image):
        self.calls += 1
        if self.change:
            self.change()
            self.change = None
        n = image.getpixel((0, 0))[0]
        status = {1: 'no_face', 2: 'multi_face'}.get(n, 'ok')
        metrics = {name: dict(raw=100, scalar=90, code=0) for name, _, _ in MINIMUMS}
        metrics.update(FaceValidation=dict(matched=True, box=[0, 0, 200, 200]), ImageSize=[40, 50])
        return dict(status=status, score=n if status == 'ok' else None, metrics=metrics, error=None)
    def close(self):
        pass


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / 'library'
    (root / '甲').mkdir(parents=True)
    store = Store(tmp_path / 'data')
    with store.connect() as db:
        db.execute('UPDATE settings SET value=?', (json.dumps(dict(folders=[str(root / "甲")], k=5, threshold=60, model='ofiq', thresholds={'ofiq':60,'faceqnet':40})),))
    engine = Engine()
    service = BaselineService(store, engine, 0, [root])
    person = service.discover()[0]
    return root / '甲', store, engine, service, person['id']


def image(directory, name, score):
    path = directory / name
    Image.new('RGB', (40, 50), (score, 20, 30)).save(path)
    return path


def scan(service):
    job = service.submit()['job']
    job['status'] = 'running'
    service.store.job(job)
    service.scan(job)
    job['finishedAt'] = now()
    service.save_job(job)
    return job


def state(store, pid):
    with store.connect() as db:
        person = db.execute('SELECT * FROM people WHERE id=?', (pid,)).fetchone()
    return serialize_person(store, person, Engine.version)


def test_incremental_metadata_duplicates_rename(setup):
    directory, store, engine, service, pid = setup
    path = image(directory, '最佳.png', 90)
    duplicate = directory / '相同.png'
    shutil.copy2(path, duplicate)
    subprocess.run(['exiftool', '-overwrite_original', '-Artist=原作者', '-Description=拍摄信息', str(path)], check=True, capture_output=True)
    original_pixels = decode(path)[1]
    assert scan(service)['scored'] == 1
    assert engine.calls == 1
    p = state(store, pid)
    assert len([x for x in p['photos'] if x['rank']]) == 1
    selected = next(x for x in p['photos'] if x['id'] == p['baselineId'])
    baseline = directory / selected['fileName']
    assert baseline.name.startswith('基线__')
    assert decode(baseline)[1] == original_pixels
    tags = json.loads(subprocess.check_output(['exiftool', '-config', str(Path(__file__).parents[1] / 'backend/face-baseline-xmp.config'), '-j', '-Artist', '-Description', '-XMP-fb:all', str(baseline)]))[0]
    assert tags['Artist'] == '原作者' if baseline.name == '基线__最佳.png' else True
    assert tags['PhotoID'] == selected['id'] and str(tags['CandidateRank']) == '1'
    assert scan(service)['scored'] == 0
    assert len(state(store, pid)['history']) == 1
    other = next(x for x in p['photos'] if x['id'] != p['baselineId'])
    renamed = directory / '用户改名.png'
    (directory / other['fileName']).rename(renamed)
    assert scan(service)['scored'] == 0
    assert any(x['id'] == other['id'] and x['name'] == renamed.name for x in state(store, pid)['photos'])
    image(directory, '新最佳.png', 99)
    assert scan(service)['scored'] == 1
    assert (directory / selected['name']).exists()
    assert not (directory / ('基线__' + selected['name'])).exists()
    assert len(state(store, pid)['history']) == 2


def test_low_quality_lock_drop_unlock_history(setup):
    directory, store, engine, service, pid = setup
    for n in (15, 30, 40): image(directory, f'{n}.png', n)
    scan(service)
    assert state(store, pid)['baselineId'] is None
    locked = state(store, pid)['photos'][0]
    service.lock(pid, locked['id'])
    p = state(store, pid)
    assert p['mode'] == 'locked' and p['baselineId'] == locked['id']
    snap = store.data / f'snapshots/{pid}/v1.png'
    snapshot_bytes = snap.read_bytes()
    for n in (70, 75, 80, 85, 90, 95): image(directory, f'{n}.png', n)
    scan(service)
    p = state(store, pid)
    assert p['baselineId'] == locked['id']
    assert not next(x for x in p['photos'] if x['id'] == locked['id'])['rank']
    assert snap.read_bytes() == snapshot_bytes
    service.unlock(pid)
    p = state(store, pid)
    assert next(x for x in p['photos'] if x['id'] == p['baselineId'])['score'] == 95
    assert (directory / locked['name']).exists()
    assert p['history'][0]['version'] == 2
    assert scan(service)['scored'] == 0


def test_excluded_and_content_change(setup):
    directory, store, engine, service, pid = setup
    for n in (1, 2, 90): image(directory, f'{n}.png', n)
    (directory / '坏.jpg').write_bytes(b'not a jpeg')
    scan(service)
    p = state(store, pid)
    assert len([x for x in p['photos'] if x['rank']]) == 1
    for ph in p['photos']:
        if ph['status'] != 'ok':
            with pytest.raises(ValueError): service.lock(pid, ph['id'])
    selected = next(x for x in p['photos'] if x['id'] == p['baselineId'])
    image(directory, selected['fileName'], 50)
    assert scan(service)['scored'] == 1
    assert state(store, pid)['baselineId'] is None
    assert state(store, pid)['history'][0]['snapshotUrl'] is None
    assert (directory / '90.png').exists()


def test_changed_while_scoring_and_unstable(setup):
    directory, store, engine, service, pid = setup
    path = image(directory, '写入.png', 90)
    engine.change = lambda: image(directory, '写入.png', 80)
    scan(service)
    assert state(store, pid)['photos'][0]['status'] == 'incomplete'
    assert state(store, pid)['baselineId'] is None
    scan(service)
    assert state(store, pid)['photos'][0]['score'] == 80
    new = image(directory, '半写入.png', 85)
    person = service.discover()[0]
    service.process(person, new, fingerprint(new), False, set())
    ph = next(x for x in state(store, pid)['photos'] if x['name'] == new.name)
    assert ph['status'] == 'incomplete'
    assert scan(service)['scored'] == 1


def test_recovery_and_collision(setup, monkeypatch):
    directory, store, engine, service, pid = setup
    image(directory, 'a.png', 80)
    # This unrelated file reserves the desired baseline filename.
    unrelated = directory / '基线__a.png'
    unrelated.write_bytes(b'occupied file')
    unchanged = unrelated.read_bytes()
    apply = service.writeback.apply
    def fail_metadata(op):
        if op['kind'] == 'metadata': raise OSError('注入写回失败')
        apply(op)
    monkeypatch.setattr(service.writeback, 'apply', fail_metadata)
    assert scan(service)['status'] == 'partial'
    p = state(store, pid)
    selected = next(x for x in p['photos'] if x['id'] == p['baselineId'])
    assert selected['fileName'] == '基线__a__' + selected['id'] + '.png'
    assert unrelated.read_bytes() == unchanged
    assert p['pendingOperations']
    # A new service object repairs the persisted journal without rescoring.
    recovered = BaselineService(store, engine, 0)
    assert scan(recovered)['scored'] == 0
    assert not state(store, pid)['pendingOperations']
    assert len(state(store, pid)['history']) == 1


def test_rename_crash_and_queue_merge(setup, monkeypatch):
    directory, store, engine, service, pid = setup
    image(directory, 'a.png', 80)
    original = service.writeback.update_stat
    def crash(photo_id, path): raise RuntimeError('模拟改名后中断')
    monkeypatch.setattr(service.writeback, 'update_stat', crash)
    assert scan(service)['status'] == 'partial'
    assert (directory / '基线__a.png').exists()
    monkeypatch.setattr(service.writeback, 'update_stat', original)
    service.writeback.repair()
    assert not state(store, pid)['pendingOperations']
    assert scan(service)['scored'] == 0
    queued = service.submit(pid)['job']
    repeated = service.submit('all')
    assert repeated['merged'] and repeated['job']['id'] == queued['id']
    assert repeated['job']['scope'] == 'all'


def test_api_validation_and_mutex(setup):
    from fastapi.testclient import TestClient
    directory, store, engine, service, pid = setup
    app = create_app(store.data, engine=engine, stable_seconds=0, browse_roots=[directory.parent])
    # No lifespan: test the HTTP boundary with the worker stopped.
    with TestClient(app) as client:
        assert client.get('/healthz').status_code == 200
        assert client.put('/api/settings', json=dict(folders=[str(directory)], k=0, threshold=60)).status_code == 422
        assert client.post('/api/scans', headers={'Origin': 'https://unrelated.example'}, json={}).status_code == 403
        assert client.post(f'/api/people/{pid}/lock', json={'photoId': 'invalid'}).status_code == 400
        lock = app.state.service.mutex
        lock.acquire()
        try:
            assert client.post(f'/api/people/{pid}/unlock').status_code == 409
        finally:
            lock.release()


def wait_job(store, job_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = next(j for j in store.jobs() if j['id'] == job_id)
        if job['finishedAt'] is not None:
            return job
        time.sleep(.02)
    raise AssertionError('扫描任务未结束')


def test_stop_waiting_for_stability_and_restart_scan(setup, monkeypatch):
    directory, store, engine, service, pid = setup
    image(directory, 'a.png', 80)
    service.stable_seconds = 60
    waiting = threading.Event()
    wait = service.cancel_scan.wait
    def stable_wait(seconds):
        waiting.set()
        return wait(seconds)
    monkeypatch.setattr(service.cancel_scan, 'wait', stable_wait)
    service.start()
    try:
        job = service.submit(pid)['job']
        assert waiting.wait(10)
        service.stop_scans()
        cancelled = wait_job(store, job['id'])
        assert cancelled['status'] == 'cancelled' and cancelled['cancelRequested']
        assert cancelled['fileProcessed'] == 0 and engine.calls == 0
        service.stable_seconds = 0
        resumed = wait_job(store, service.submit(pid)['job']['id'])
        assert resumed['status'] == 'done' and resumed['scored'] == 1
        assert not resumed['cancelRequested']
    finally:
        service.close()


def test_stop_during_scoring_preserves_unvisited_photos_locks_and_cache(setup, monkeypatch):
    from backend.service import BusyError
    directory, store, engine, service, pid = setup
    image(directory, 'a.png', 65)
    image(directory, 'b.png', 75)
    scan(service)
    service.lock(pid, state(store, pid)['baselineId'])
    before = state(store, pid)
    snapshots = {p: p.read_bytes() for p in (store.data / 'snapshots').rglob('*.png')}
    image(directory, '0-new.png', 95)
    image(directory, 'z-new.png', 85)
    scoring, release = threading.Event(), threading.Event()
    def block_score():
        scoring.set()
        assert release.wait(10)
    engine.change = block_score
    service.start()
    try:
        job = service.submit(pid)['job']
        assert scoring.wait(10)
        queued = service.submit('all')['job']
        service.stop_scans()
        assert next(j for j in store.jobs() if j['id'] == queued['id'])['status'] == 'cancelled'
        running = next(j for j in store.jobs() if j['id'] == job['id'])
        running['cancelRequested'] = False  # Simulate stale worker progress saved after the request.
        service.save_job(running)
        assert running['cancelRequested']
        with pytest.raises(BusyError):
            service.submit(pid)
        release.set()
        cancelled = wait_job(store, job['id'])
        assert cancelled['status'] == 'cancelled'
        assert cancelled['fileProcessed'] == 1 and cancelled['scored'] == 1
        after = state(store, pid)
        assert len(after['photos']) == 3
        assert {p['id'] for p in before['photos']} <= {p['id'] for p in after['photos']}
        assert after['baselineId'] == before['baselineId'] and after['lockedPhotoId'] == before['lockedPhotoId']
        assert after['history'] == before['history']
        assert not after['pendingOperations']
        assert all(p.read_bytes() == data for p, data in snapshots.items())
        assert next(p for p in after['photos'] if p['name'] == '0-new.png')['rank'] == 1
        resumed = wait_job(store, service.submit(pid)['job']['id'])
        assert resumed['status'] == 'done' and resumed['scored'] == 1
        assert len(state(store, pid)['photos']) == 4
    finally:
        release.set()
        service.close()


def test_stop_api_cancels_queue_without_scan_mutex_and_survives_restart(setup):
    from fastapi.testclient import TestClient
    directory, store, engine, service, pid = setup
    app = create_app(store.data, engine=engine, stable_seconds=0, browse_roots=[directory.parent])
    client = TestClient(app)
    queued = app.state.service.submit(pid)['job']
    app.state.service.mutex.acquire()
    try:
        assert client.post('/api/scans/stop', headers={'Origin': 'https://other.example'}).status_code == 403
        response = client.post('/api/scans/stop')
        assert response.status_code == 202
        assert response.json()['jobs'][0]['status'] == 'cancelled'
        assert client.post('/api/scans/stop').json() == {'jobs': []}
    finally:
        app.state.service.mutex.release()
        client.close()
    assert next(j for j in store.jobs() if j['id'] == queued['id'])['status'] == 'cancelled'
    queued.update(status='running', cancelRequested=True, finishedAt=None)
    store.job(queued)
    service.start()
    try:
        assert next(j for j in store.jobs() if j['id'] == queued['id'])['status'] == 'cancelled'
        assert engine.calls == 0
    finally:
        service.close()


def compressed_payload(path):
    data = path.read_bytes()
    if path.suffix.lower() == '.jpg':
        return data[data.index(b'\xff\xda'):]
    chunks, cursor = [], 8
    while cursor < len(data):
        length = struct.unpack('>I', data[cursor:cursor + 4])[0]
        if data[cursor + 4:cursor + 8] == b'IDAT':
            chunks.append(data[cursor + 8:cursor + 8 + length])
        cursor += length + 12
    return b''.join(chunks)


@pytest.mark.parametrize('extension', ['.jpg', '.png'])
def test_preserves_compressed_image_and_capture_metadata(setup, extension):
    directory, store, engine, service, pid = setup
    path = image(directory, '原片' + extension, 90)
    subprocess.run(['exiftool', '-overwrite_original', '-Artist=原作者', '-DateTimeOriginal=2020:05:06 12:13:14', str(path)], check=True, capture_output=True)
    payload = compressed_payload(path)
    scan(service)
    selected = next(x for x in state(store, pid)['photos'] if x['id'] == state(store, pid)['baselineId'])
    renamed = directory / selected['fileName']
    assert compressed_payload(renamed) == payload
    tags = json.loads(subprocess.check_output(['exiftool', '-j', '-Artist', '-DateTimeOriginal', str(renamed)]))[0]
    assert tags['Artist'] == '原作者' and tags['DateTimeOriginal'] == '2020:05:06 12:13:14'


def test_two_observations_detect_partial_write(setup, monkeypatch):
    directory, store, engine, service, pid = setup
    path = image(directory, '写入中.png', 90)
    service.stable_seconds = 0.15
    wait = service.cancel_scan.wait
    def write_during_observation_gap(seconds):
        image(directory, path.name, 85)
        return wait(seconds)
    monkeypatch.setattr(service.cancel_scan, 'wait', write_during_observation_gap)
    scan(service)
    monkeypatch.setattr(service.cancel_scan, 'wait', wait)
    assert engine.calls == 0
    assert state(store, pid)['photos'][0]['status'] == 'incomplete'
    assert scan(service)['scored'] == 1


def test_unchanged_people_do_not_rerank(setup, monkeypatch):
    directory, store, engine, service, pid = setup
    image(directory, 'a.png', 80)
    scan(service)
    def unexpected(*args): raise AssertionError('未变化人物不应重新排名')
    monkeypatch.setattr(service, 'reconcile', unexpected)
    assert scan(service)['scored'] == 0


def test_baseline_changed_during_write_restores_name_next_scan(setup):
    directory, store, engine, service, pid = setup
    image(directory, 'a.png', 90)
    scan(service)
    person = service.discover()[0]
    path = directory / '基线__a.png'
    image(directory, path.name, 30)
    service.process(person, path, fingerprint(path), False, set())
    service.reconcile(pid, '写入期间暂缺基线')
    service.writeback.repair(pid)
    scan(service)
    assert (directory / 'a.png').exists()
    assert not path.exists()
    assert state(store, pid)['baselineId'] is None


def test_locking_identical_copy_keeps_one_candidate(setup):
    directory, store, engine, service, pid = setup
    image(directory, 'a.png', 90)
    shutil.copy2(directory / 'a.png', directory / 'copy.png')
    scan(service)
    p = state(store, pid)
    copy = next(ph for ph in p['photos'] if ph['id'] != p['baselineId'])
    service.lock(pid, copy['id'])
    p = state(store, pid)
    assert p['baselineId'] == copy['id']
    assert len([ph for ph in p['photos'] if ph['rank']]) == 1
    assert next(ph for ph in p['photos'] if ph['id'] == copy['id'])['rank'] == 1


def test_explicit_folders_recursion_and_unselected_siblings(setup):
    directory, store, engine, service, pid = setup
    root = directory.parent
    sibling = root / '不选入'; sibling.mkdir()
    image(sibling, 'skip.png', 99)
    nested = directory / '子目录'; nested.mkdir()
    image(nested, 'inside.png', 80)
    new_folder = root / '新出现'; new_folder.mkdir()
    image(new_folder, 'skip.png', 90)
    assert scan(service)['scored'] == 1
    assert len(service.discover()) == 1
    assert state(store, pid)['photos'][0]['name'] == 'inside.png'
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM people').fetchone()[0] == 1


def test_multiselect_same_names_and_preserve_removed_archive(setup):
    directory, store, engine, service, pid = setup
    image(directory, 'a.png', 90)
    scan(service)
    photo = state(store, pid)['photos'][0]
    service.lock(pid, photo['id'])
    original = state(store, pid)
    other_parent = directory.parent / '另一个位置'; other_parent.mkdir()
    other = other_parent / directory.name; other.mkdir()
    image(other, 'b.png', 85)
    service.settings(dict(folders=[str(directory), str(other)], k=5, threshold=60))
    assert len(service.discover()) == 2
    assert scan(service)['scored'] == 1
    service.settings(dict(folders=[str(other)], k=5, threshold=60))
    assert state(store, pid)['lockedPhotoId'] == original['lockedPhotoId']
    assert state(store, pid)['history'] == original['history']
    with pytest.raises(ValueError): service.submit(pid)
    service.settings(dict(folders=[str(directory), str(other)], k=5, threshold=60))
    assert service.discover()[0]['id'] == pid
    assert scan(service)['scored'] == 0
    assert state(store, pid)['lockedPhotoId'] == photo['id']


def test_folder_browse_and_overlapping_selection(setup):
    directory, store, engine, service, pid = setup
    root = directory.parent
    assert service.browse()['directories'][0]['path'] == str(root)
    assert service.browse(str(root))['directories'][0]['path'] == str(directory)
    with pytest.raises(ValueError): service.browse(str(root.parent))
    with pytest.raises(ValueError): service.settings(dict(folders=[str(root), str(directory)], k=5, threshold=60))
    with pytest.raises(ValueError): service.settings(dict(folders=[str(directory), str(directory)], k=5, threshold=60))
    service.settings(dict(folders=[], k=5, threshold=60))
    assert service.discover() == []
    with pytest.raises(ValueError): service.submit()


def test_selected_nested_folder_reuses_score_and_photo_identity(setup):
    directory, store, engine, service, pid = setup
    nested = directory / 'nested'; nested.mkdir()
    image(nested, 'a.png', 90)
    scan(service)
    old = state(store, pid)
    photo_id = old['photos'][0]['id']
    service.settings(dict(folders=[str(nested)], k=5, threshold=60))
    nested_id = service.discover()[0]['id']
    assert scan(service)['scored'] == 0
    assert state(store, nested_id)['photos'][0]['id'] == photo_id
    assert state(store, pid)['history'] == old['history']
    service.settings(dict(folders=[str(directory)], k=5, threshold=60))
    assert service.discover()[0]['id'] == pid
    assert scan(service)['scored'] == 0


def test_legacy_migration_and_manual_restart(setup):
    import time
    directory, store, engine, service, pid = setup
    image(directory, 'a.png', 90)
    scan(service)
    old = state(store, pid)
    with store.connect() as db:
        db.execute('UPDATE settings SET value=?', (json.dumps(dict(root=str(directory.parent), k=5, threshold=60, model='ofiq', thresholds={'ofiq':60,'faceqnet':40})),))
    migrated = Store(store.data)
    assert migrated.settings() == dict(folders=[str(directory)], k=5, threshold=60, model='ofiq', thresholds={'ofiq':60,'faceqnet':40})
    assert state(migrated, pid) == old
    queued = service.submit()['job']
    restart = BaselineService(migrated, engine, 0, [directory.parent])
    calls = engine.calls
    restart.start()
    try:
        time.sleep(0.05)
        assert engine.calls == calls
        interrupted = next(j for j in migrated.jobs() if j['id'] == queued['id'])
        assert interrupted['status'] == 'failed'
        assert state(migrated, pid) == old
    finally:
        restart.close()


def test_quality_gates_precede_total_and_keep_manual_low_quality(setup):
    directory, store, engine, service, pid = setup
    image(directory, '高分模糊.png', 99)
    image(directory, '清晰合格.png', 65)
    scan(service)
    with store.connect() as db:
        high = db.execute('SELECT * FROM photos WHERE score=99').fetchone()
        metrics = json.loads(high['metrics']); metrics['Sharpness']['scalar'] = 14
        db.execute('UPDATE photos SET metrics=? WHERE id=?', (json.dumps(metrics), high['id']))
    service.settings(dict(folders=[str(directory)], k=1, threshold=60))
    p = state(store, pid)
    baseline = next(x for x in p['photos'] if x['id'] == p['baselineId'])
    assert baseline['score'] == 65 and baseline['qualified']
    blurry = next(x for x in p['photos'] if x['score'] == 99)
    assert blurry['eligible'] and not blurry['qualified'] and blurry['qualityIssues']
    service.lock(pid, blurry['id'])
    assert state(store, pid)['baselineId'] == blurry['id']
    assert not next(x for x in state(store, pid)['photos'] if x['id'] == blurry['id'])['qualified']
    service.unlock(pid)
    assert state(store, pid)['baselineId'] == baseline['id']


def test_engine_upgrade_invalidates_fast_path_and_preserves_history(setup, monkeypatch):
    directory, store, engine, service, pid = setup
    image(directory, 'a.png', 90)
    scan(service)
    original = state(store, pid)
    photo_id = original['baselineId']
    service.lock(pid, photo_id)
    snapshot = store.data / f'snapshots/{pid}/v1.png'
    before = snapshot.read_bytes()
    monkeypatch.setattr(Engine, 'version', 'acceptance-fixture-v2')
    service.upgrade_rules()
    pending = state(store, pid)
    assert pending['baselineId'] is None and pending['lockedPhotoId'] == photo_id
    assert not pending['photos'][0]['eligible']
    assert (directory / 'a.png').exists()
    with pytest.raises(ValueError): service.lock(pid, photo_id)
    assert scan(service)['scored'] == 1
    reviewed = state(store, pid)
    assert reviewed['baselineId'] == photo_id and reviewed['lockedPhotoId'] == photo_id
    assert snapshot.read_bytes() == before
    assert scan(service)['scored'] == 0


def test_verified_single_face_required_and_missing_metrics_not_auto(setup):
    directory, store, engine, service, pid = setup
    image(directory, 'a.png', 95)
    scan(service)
    with store.connect() as db:
        photo = db.execute('SELECT * FROM photos').fetchone()
        metrics = json.loads(photo['metrics']); metrics.pop('InterEyeDistance')
        db.execute('UPDATE photos SET metrics=? WHERE id=?', (json.dumps(metrics), photo['id']))
    service.reconcile(pid, '人脸有效像素无法评估'); service.writeback.repair(pid)
    assert state(store, pid)['baselineId'] is None
    assert state(store, pid)['photos'][0]['eligible']
    assert not state(store, pid)['photos'][0]['qualified']
    metrics['FaceValidation']['matched'] = False
    with store.connect() as db:
        db.execute('UPDATE photos SET metrics=? WHERE id=?', (json.dumps(metrics), photo['id']))
    service.reconcile(pid, '检测位置不一致'); service.writeback.repair(pid)
    assert not state(store, pid)['photos'][0]['rank']
    with pytest.raises(ValueError): service.lock(pid, photo['id'])


def test_review_interrupted_before_ranking_is_recovered(setup):
    directory, store, engine, service, pid = setup
    service.upgrade_rules()
    path = image(directory, 'a.png', 90)
    person = service.discover()[0]
    service.process(person, path, fingerprint(path), True, set())
    assert state(store, pid)['baselineId'] is None
    # Recreate the service after the photo commit, before the person ranking.
    restart = BaselineService(store, engine, 0, [directory.parent])
    restart.upgrade_rules()
    assert state(store, pid)['baselineId'] is not None
    assert engine.calls == 1
    assert scan(restart)['scored'] == 0
