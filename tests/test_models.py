import json
from pathlib import Path

from backend.app import serialize_person, serialize_people
from backend.service import BaselineService
from backend.store import Store
from test_acceptance import Engine, image, scan, setup


def test_default_and_legacy_threshold_migration(tmp_path):
    store = Store(tmp_path / 'data')
    settings = store.settings()
    assert settings['model'] == 'faceqnet' and settings['threshold'] == 40
    assert settings['thresholds'] == {'faceqnet':40,'ofiq':60}
    with store.connect() as db:
        db.execute('UPDATE settings SET value=?', (json.dumps(dict(folders=[],k=5,threshold=73)),))
    migrated = Store(store.data).settings()
    assert migrated['model'] == 'faceqnet' and migrated['threshold'] == 40
    assert migrated['thresholds']['ofiq'] == 73


def test_bulk_gallery_preserves_individual_records(setup):
    directory, store, engine, service, pid = setup
    second = directory.parent / '乙'
    second.mkdir()
    image(directory, 'a.png', 90)
    image(second, 'b.png', 80)
    service.settings(dict(folders=[str(directory), str(second)], k=5, threshold=60, model='ofiq'))
    scan(service)
    with store.connect() as db:
        people = db.execute('SELECT * FROM people ORDER BY name,id').fetchall()
        for person in people:
            store_id = db.execute('SELECT id FROM photos WHERE person_id=?', (person['id'],)).fetchone()[0]
            db.execute("INSERT INTO operations(person_id,photo_id,kind,payload,created,error) VALUES(?,?,'metadata','{}',1,?)",
                       (person['id'],store_id,person['name']))
    bulk = serialize_people(store, people, engine.version)
    assert bulk == [serialize_person(store, p, engine.version) for p in people]
    assert {p['name']: p['photos'][0]['name'] for p in bulk} == {'甲':'a.png', '乙':'b.png'}
    assert all(p['pendingOperations'][0]['error'] == p['name'] for p in bulk)
    assert all(p['history'][0]['snapshotUrl'] for p in bulk)


def test_model_switch_preserves_lock_history_and_uses_separate_caches(setup):
    directory, store, original, service, pid = setup
    image(directory, 'a.png', 90)
    image(directory, 'b.png', 80)
    scan(service)

    def state():
        with store.connect() as db:
            p = db.execute('SELECT * FROM people WHERE id=?',(pid,)).fetchone()
        return serialize_person(store,p,service.engine.version)

    service.lock(pid,state()['baselineId'])
    before = state()
    snapshots = {p:p.read_bytes() for p in (store.data/'snapshots').rglob('*.png')}
    class Alternative(Engine):
        version = 'FaceQnet-fixture/acceptance-fixture'
        def score(self,img):
            result = super().score(img)
            result['score'] = 120-result['score']
            return result
    alternative = Alternative()
    service.engine_factory = lambda model: alternative if model=='faceqnet' else original
    service.settings(dict(folders=[str(directory)],k=5,threshold=40,model='faceqnet'))
    pending = state()
    assert pending['baselineId']==before['baselineId'] and pending['lockedPhotoId']==before['lockedPhotoId']
    assert pending['history']==before['history']
    assert not pending['photos'][0]['eligible']
    assert scan(service)['scored']==2
    assert state()['baselineId']==before['baselineId']
    assert not next(p for p in state()['photos'] if p['id']==before['baselineId'])['qualified']
    service.settings(dict(folders=[str(directory)],k=5,threshold=60,model='ofiq'))
    assert next(p for p in state()['photos'] if p['id']==before['baselineId'])['score']==90
    assert scan(service)['scored']==0 and original.calls==2
    service.settings(dict(folders=[str(directory)],k=5,threshold=40,model='faceqnet'))
    assert scan(service)['scored']==0 and alternative.calls==2
    service.unlock(pid)
    chosen = next(p for p in state()['photos'] if p['id']==state()['baselineId'])
    assert chosen['name']=='b.png' and chosen['score']==40 and chosen['qualified']
    assert state()['history'][0]['model']=='faceqnet'
    assert all(p.read_bytes()==content for p,content in snapshots.items())
    assert store.settings()['thresholds']=={'ofiq':60,'faceqnet':40}
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM scores').fetchone()[0]==4
