import json
import shutil
import subprocess
import threading
import struct
from pathlib import Path

import pytest
from PIL import Image

from backend.app import create_app, serialize_person
from backend.images import decode, fingerprint
from backend.service import BaselineService
from backend.store import Store, now


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
        return dict(status=status, score=n if status == 'ok' else None, metrics={}, error=None)
    def close(self):
        pass


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / 'library'
    (root / '甲').mkdir(parents=True)
    store = Store(tmp_path / 'data')
    with store.connect() as db:
        db.execute('UPDATE settings SET value=?', (json.dumps(dict(root=str(root), k=5, threshold=60)),))
    engine = Engine()
    service = BaselineService(store, engine, 0)
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
    return serialize_person(store, person)


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
    app = create_app(store.data, engine=engine, stable_seconds=0)
    # No lifespan: test the HTTP boundary with the worker stopped.
    with TestClient(app) as client:
        assert client.get('/healthz').status_code == 200
        assert client.put('/api/settings', json=dict(root=str(directory.parent), k=0, threshold=60)).status_code == 422
        assert client.post('/api/scans', headers={'Origin': 'https://unrelated.example'}, json={}).status_code == 403
        assert client.post(f'/api/people/{pid}/lock', json={'photoId': 'invalid'}).status_code == 400
        lock = app.state.service.mutex
        lock.acquire()
        try:
            assert client.post(f'/api/people/{pid}/unlock').status_code == 409
        finally:
            lock.release()


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
    import time
    sleep = time.sleep
    def write_during_observation_gap(seconds):
        image(directory, path.name, 85)
        sleep(seconds)
    monkeypatch.setattr('backend.service.time.sleep', write_during_observation_gap)
    scan(service)
    monkeypatch.setattr('backend.service.time.sleep', sleep)
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
