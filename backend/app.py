import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import OfiqEngine
from .service import BaselineService, BusyError
from .store import Store
from .quality import assess


class Settings(BaseModel):
    folders: list[str]
    k: int = Field(ge=1, le=100)
    threshold: int = Field(ge=0, le=100)


class Lock(BaseModel):
    photoId: str


class Scan(BaseModel):
    scope: str = 'all'


def serialize_person(store, person, engine_version=OfiqEngine.version):
    settings = store.settings()
    with store.connect() as db:
        photos = db.execute('SELECT * FROM photos WHERE person_id=? AND present=1 ORDER BY added,id', (person['id'],)).fetchall()
        histories = db.execute('SELECT * FROM history WHERE person_id=? ORDER BY version DESC', (person['id'],)).fetchall()
        ops = [dict(r) for r in db.execute("SELECT id,kind,photo_id,error FROM operations WHERE person_id=? AND status='pending'", (person['id'],))]
    result = dict(id=person['id'], name=person['name'], directory=person['directory'], available=Path(person['directory']).is_dir(), lockedPhotoId=person['locked_id'],
                  baselineId=person['baseline_id'], mode=person['mode'], lastScan=person['last_scan'],
                  version=person['version'], pendingOperations=ops, photos=[], history=[])
    for p in photos:
        metrics = json.loads(p['metrics'] or '{}')
        quality = assess(p, settings['threshold'], engine_version)
        def scalar(name):
            item = metrics.get(name)
            return item['scalar'] if isinstance(item, dict) and item['code'] == 0 and item['scalar'] is not None and item['scalar'] >= 0 else None
        subs = dict(sharpness=scalar('Sharpness'), lighting=scalar('IlluminationUniformity'),
                    eyes=scalar('EyesVisible'), pose=scalar('HeadPoseYaw'), occlusion=scalar('FaceOcclusionPrevention'))
        thumb = store.data / 'thumbnails' / (p['id'] + '.jpg')
        result['photos'].append(dict(id=p['id'], name=p['original_name'], fileName=Path(p['path']).name,
                                    url=f'/api/photos/{p["id"]}/file' if thumb.exists() and p['status'] != 'incomplete' else None,
                                    thumbnailUrl=f'/api/photos/{p["id"]}/thumbnail' if thumb.exists() and p['status'] != 'incomplete' else None,
                                    status=p['status'], score=p['score'], sub=subs if p['status'] == 'ok' else None,
                                    metrics=metrics, engine=p['engine'], error=p['error'],
                                    eligible=quality['eligible'], qualified=quality['qualified'], qualityIssues=quality['issues'],
                                    assessmentFace=metrics.get('FaceValidation', {}).get('box'), imageSize=metrics.get('ImageSize'),
                                    hash=p['hash'] or p['id'], addedAt=p['added'], rank=p['rank'], writeback=p['writeback']))
    for h in histories:
        available = h['snapshot'] and (store.data / h['snapshot']).is_file()
        result['history'].append(dict(version=h['version'], at=h['at'], reason=h['reason'],
                                      mode='none' if h['mode'] == 'missing' else h['mode'], photoId=h['photo_id'],
                                      fileName=h['file_name'], score=h['score'],
                                      snapshotUrl=f'/api/people/{person["id"]}/history/{h["version"]}/snapshot' if available else None))
    return result


def create_app(data=None, engine=None, stable_seconds=10, web=None, browse_roots=None):
    store = Store(Path(data or os.environ.get('FACE_BASELINE_DATA', '/data')))
    engine = engine or OfiqEngine()
    roots = browse_roots or json.loads(os.environ.get('FACE_BASELINE_LIBRARY_BASES', '["/vol3/1000/Picture/YY/人物"]'))
    service = BaselineService(store, engine, stable_seconds, roots)

    @asynccontextmanager
    async def lifespan(app):
        try:
            service.discover()
        except OSError:
            pass  # Mount errors remain visible in health and scans; the settings page stays usable.
        service.start()
        service.upgrade_rules()
        yield
        service.close()
        engine.close()

    app = FastAPI(title='人脸基线', version='1.2.0', lifespan=lifespan)
    app.state.service = service

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.exception_handler(BusyError)
    async def busy(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=409)

    @app.middleware('http')
    async def same_origin(request: Request, call_next):
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            origin = request.headers.get('origin')
            if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': '仅允许本站操作'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/healthz')
    def health():
        folders = store.settings()['folders']
        return {'status': 'ok', 'libraryAvailable': bool(folders) and all(Path(p).is_dir() for p in folders), 'engine': engine.version}

    @app.get('/api/state')
    def state():
        settings = store.settings()
        with store.connect() as db:
            people = db.execute('SELECT * FROM people ORDER BY name,id').fetchall()
        return dict(settings=settings,
                    people=[serialize_person(store, p, engine.version) for p in people if p['directory'] in settings['folders']],
                    jobs=store.jobs(), libraryAvailable=bool(settings['folders']) and all(Path(p).is_dir() for p in settings['folders']), engine=engine.version)

    @app.get('/api/folders')
    def folders(path: str | None = None):
        return service.browse(path)

    @app.get('/api/people')
    def people():
        return state()['people']

    @app.get('/api/people/{person_id}')
    def person(person_id: str):
        with store.connect() as db:
            p = db.execute('SELECT * FROM people WHERE id=?', (person_id,)).fetchone()
        if not p:
            raise HTTPException(404, '找不到该人物')
        return serialize_person(store, p, engine.version)

    @app.get('/api/people/{person_id}/candidates')
    def candidates(person_id: str):
        p = person(person_id)
        return {'top': sorted([x for x in p['photos'] if x['rank']], key=lambda x: x['rank']),
                'locked': next((x for x in p['photos'] if x['id'] == p['lockedPhotoId']), None)}

    @app.get('/api/people/{person_id}/history')
    def history(person_id: str):
        return person(person_id)['history']

    @app.post('/api/people/{person_id}/lock')
    def lock(person_id: str, body: Lock):
        service.lock(person_id, body.photoId)
        return person(person_id)

    @app.post('/api/people/{person_id}/unlock')
    def unlock(person_id: str):
        service.unlock(person_id)
        return person(person_id)

    @app.put('/api/settings')
    def settings(body: Settings):
        service.settings(body.model_dump())
        return state()

    @app.post('/api/scans', status_code=202)
    def scan(body: Scan):
        return service.submit(body.scope)

    @app.get('/api/scans')
    def scans():
        return store.jobs()

    @app.get('/api/scans/{job_id}')
    def job(job_id: str):
        found = next((j for j in store.jobs() if j['id'] == job_id), None)
        if not found:
            raise HTTPException(404, '找不到该扫描任务')
        return found

    @app.get('/api/photos/{photo_id}/{kind}')
    def photo_file(photo_id: str, kind: str):
        with store.connect() as db:
            p = db.execute('SELECT * FROM photos WHERE id=? AND present=1', (photo_id,)).fetchone()
        if not p or kind not in ('file', 'thumbnail'):
            raise HTTPException(404, '找不到照片')
        path = Path(p['path']) if kind == 'file' else store.data / 'thumbnails' / (photo_id + '.jpg')
        if not path.is_file():
            raise HTTPException(404, '照片文件不可用')
        return FileResponse(path, filename=path.name if kind == 'file' else None, content_disposition_type='inline')

    @app.get('/api/people/{person_id}/history/{version}/snapshot')
    def snapshot(person_id: str, version: int):
        with store.connect() as db:
            h = db.execute('SELECT * FROM history WHERE person_id=? AND version=?', (person_id, version)).fetchone()
        if not h or not h['snapshot'] or not (store.data / h['snapshot']).exists():
            raise HTTPException(404, '快照尚未保存或不存在，请查看待修复记录')
        return FileResponse(store.data / h['snapshot'], filename=f'v{version}_{h["file_name"]}', content_disposition_type='inline')

    web = Path(web or os.environ.get('FACE_BASELINE_WEB', '/app/web'))
    if web.is_dir():
        app.mount('/', StaticFiles(directory=web, html=True), name='web')
    return app
