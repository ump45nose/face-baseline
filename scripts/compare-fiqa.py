"""Read-only comparison of official SER-FIQ and FaceQnet on one library."""
import argparse
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import urllib.request

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
            'MXNET_CPU_WORKER_NTHREADS', 'TF_NUM_INTRAOP_THREADS'):
    os.environ[key] = '2'
os.environ['TF_NUM_INTEROP_THREADS'] = '1'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SEEDS = [7, 19, 41]


def load(root):
    return json.loads((root / 'results.json').read_text())


def save(root, result):
    (root / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(args):
    from backend.images import decode
    root = args.output
    (root / 'inputs').mkdir(parents=True, exist_ok=True)
    person = json.load(urllib.request.urlopen(args.api + '/people/' + args.person))
    with sqlite3.connect(f'file:{args.database}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        paths = {r['id']: dict(r) for r in db.execute('SELECT id,path,hash FROM photos WHERE person_id=? AND present=1', (args.person,))}
    result = dict(person=person['name'], personId=args.person, k=5,
                  created=time.strftime('%Y-%m-%d %H:%M:%S'), photos=[],
                  before=dict(baselineId=person['baselineId'], lockedPhotoId=person['lockedPhotoId'], history=person['history']),
                  models=dict(serfiq=dict(repo='https://github.com/pterhoer/FaceImageQuality',
                                         commit='611296605db57b8d50518fd5911d5111eeb52747',
                                         passes=100, seeds=SEEDS, alpha=130, r=.88),
                              faceqnet=dict(repo='https://github.com/uam-biometrics/FaceQnet',
                                            commit='c8ae6957c4a2544f23b4433f5af09321dea29e7d', version='v1')))
    for photo in sorted(person['photos'], key=lambda p: p['name']):
        source = Path(paths[photo['id']]['path'])
        image, digest = decode(source)
        assert digest == paths[photo['id']]['hash'], f'扫描后内容变化：{source.name}'
        image.save(root / 'inputs' / (photo['id'] + '.png'))
        result['photos'].append(dict(id=photo['id'], name=photo['name'], path=str(source), hash=digest,
                                    fileSha=sha(source), status=photo['status'], ofiq=photo['score'],
                                    ofiqRank=photo['rank'], qualified=photo['qualified'], issues=photo['qualityIssues']))
    save(root, result)
    print('Prepared', len(result['photos']), 'photos', flush=True)


def cut_symbol(mx, graph, boundary):
    """Cut the original graph after a given node, preserving all subsequent ops."""
    names = {n['name']: i for i, n in enumerate(graph['nodes'])}
    index = names[boundary]
    nodes = [dict(op='null', name='features', inputs=[])]
    remap = {index: 0}
    for i in range(index + 1, len(graph['nodes'])):
        n = copy.deepcopy(graph['nodes'][i])
        n['inputs'] = [[remap[a], b, c] for a, b, c in n['inputs']]
        remap[i] = len(nodes)
        nodes.append(n)
    head = dict(nodes=nodes, arg_nodes=[i for i, n in enumerate(nodes) if n['op'] == 'null'],
                node_row_ptr=list(range(len(nodes) + 1)),
                heads=[[remap[a], b, c] for a, b, c in graph['heads']], attrs=graph['attrs'])
    return mx.sym.load_json(json.dumps(head))


def serfiq(args):
    import cv2
    import numpy as np
    import mxnet as mx
    sys.path.insert(0, str(args.ser_source))
    from face_image_quality import SER_FIQ
    from insightface.src.mtcnn_detector import MtcnnDetector
    from insightface.src import face_preprocess

    root, result = args.output, load(args.output)
    model_dir = root / 'serfiq-model'
    graph = json.loads((model_dir / 'insightface-symbol.json').read_text())
    original = mx.sym.load_json(json.dumps(graph))
    params = mx.nd.load(str(model_dir / 'insightface-0000.params'))
    arg = {k[4:]: v for k, v in params.items() if k.startswith('arg:')}
    aux = {k[4:]: v for k, v in params.items() if k.startswith('aux:')}

    def module(symbol, name, shape):
        m = mx.mod.Module(symbol=symbol, data_names=(name,), label_names=None, context=mx.cpu())
        m.bind(for_training=False, data_shapes=[(name, shape)])
        m.set_params(arg, aux, allow_extra=True)
        return m

    backbone = module(original.get_internals()['bn1_output'], 'data', (1, 3, 112, 112))
    backbone.forward(mx.io.DataBatch([mx.nd.zeros((1, 3, 112, 112))]), is_train=False)
    feature_shape = tuple(backbone.get_outputs()[0].shape[1:])
    head = module(cut_symbol(mx, graph, 'bn1'), 'features', (100, *feature_shape))

    class SplitNetwork:
        def __call__(self, batch):
            # All 100 inputs are identical in upstream get_score(). The sole dropout
            # is after bn1, so the deterministic backbone only needs one pass.
            backbone.forward(mx.io.DataBatch([batch[:1]]), is_train=False)
            features = mx.nd.repeat(backbone.get_outputs()[0], repeats=batch.shape[0], axis=0)
            head.forward(mx.io.DataBatch([features]), is_train=False)
            return head.get_outputs()[0]

    ser = SER_FIQ.__new__(SER_FIQ)
    ser.device, ser.det, ser.preprocess = mx.cpu(), 0, face_preprocess.preprocess
    ser.insightface = SplitNetwork()
    ser.detector = MtcnnDetector(model_folder=str(args.ser_source / 'insightface/mtcnn-model'),
                                 ctx=ser.device, num_worker=1, accurate_landmark=True, threshold=[.6, .7, .8])
    model_info = result['models']['serfiq']
    model_info['symbolSha256'] = sha(model_dir / 'insightface-symbol.json')
    model_info['weightsSha256'] = sha(model_dir / 'insightface-0000.params')
    model_info['optimization'] = 'Original graph split after bn1; 1 deterministic backbone pass, 100 original stochastic head passes.'
    validated = False
    (root / 'aligned').mkdir(exist_ok=True)
    (root / 'faceqnet-inputs').mkdir(exist_ok=True)
    for photo in result['photos']:
        if photo['status'] != 'ok':
            continue
        image = cv2.imread(str(root / 'inputs' / (photo['id'] + '.png')))
        detected = ser.detector.detect_face(image, det_type=ser.det)
        if detected is None or len(detected[0]) != 1:
            photo['comparisonError'] = 'MTCNN 未确认单人'
            save(root, result)
            continue
        bbox, points = detected
        landmarks = points[0].reshape((2, 5)).T
        aligned_bgr = ser.preprocess(image, bbox, landmarks, image_size='112,112')
        aligned = np.transpose(cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2RGB), (2, 0, 1))
        cv2.imwrite(str(root / 'aligned' / (photo['id'] + '.png')), aligned_bgr)
        h, w = image.shape[:2]
        x1, y1 = np.maximum(np.floor(bbox[0, :2]).astype(int), 0)
        x2, y2 = np.minimum(np.ceil(bbox[0, 2:4]).astype(int), [w, h])
        crop = image[y1:y2, x1:x2]
        cv2.imwrite(str(root / 'faceqnet-inputs' / (photo['id'] + '.png')), cv2.resize(crop, (224, 224)))
        photo['faceBox'] = [int(x1), int(y1), int(x2), int(y2)]
        if not validated:
            # Validate both sides of the split against the full official graph.
            reference = module(mx.sym.Group([original.get_internals()['bn1_output'],
                                             original.get_internals()['dropout0_output'], original]),
                               'data', (2, 3, 112, 112))
            reference.forward(mx.io.DataBatch([mx.nd.array(np.repeat(aligned[None], 2, axis=0))]), is_train=False)
            full_features, masks, expected = reference.get_outputs()
            backbone.forward(mx.io.DataBatch([mx.nd.array(aligned[None])]), is_train=False)
            feature_error = float(np.max(np.abs(backbone.get_outputs()[0].asnumpy() - full_features[:1].asnumpy())))
            replay = module(cut_symbol(mx, graph, 'dropout0'), 'features', masks.shape)
            replay.forward(mx.io.DataBatch([masks]), is_train=False)
            head_error = float(np.max(np.abs(replay.get_outputs()[0].asnumpy() - expected.asnumpy())))
            assert feature_error < .001 and head_error < .001, (feature_error, head_error)
            model_info['validation'] = dict(backboneMaxAbsError=feature_error, headMaxAbsError=head_error)
            del reference, replay
            validated = True
        started = time.monotonic()
        samples = []
        for seed in SEEDS:
            mx.random.seed(seed)
            samples.append(float(ser.get_score(aligned, T=100)))
        photo['serfiqSamples'] = samples
        photo['serfiq'] = float(np.mean(samples))
        photo['serfiqStd'] = float(np.std(samples))
        photo['serfiqSeconds'] = round(time.monotonic() - started, 3)
        save(root, result)
        print(photo['name'], 'SER-FIQ', photo['serfiq'], samples, flush=True)


def faceqnet(args):
    import cv2
    import numpy as np
    from tensorflow.keras.models import load_model
    root, result = args.output, load(args.output)
    model = load_model(str(root / 'FaceQnet_v1.h5'), compile=False)
    result['models']['faceqnet']['weightsSha256'] = sha(root / 'FaceQnet_v1.h5')
    result['models']['faceqnet']['preprocessing'] = 'Same MTCNN face box, resize 224x224, BGR float32 0..255, no extra normalization; official batch_size=1.'
    for photo in result['photos']:
        if 'serfiq' not in photo:
            continue
        image = cv2.imread(str(root / 'faceqnet-inputs' / (photo['id'] + '.png')))
        started = time.monotonic()
        raw = float(model.predict(image[None].astype(np.float32), batch_size=1, verbose=0)[0, 0])
        photo['faceqnetRaw'] = raw
        photo['faceqnet'] = min(1., max(0., raw))
        photo['faceqnetSeconds'] = round(time.monotonic() - started, 3)
        save(root, result)
        print(photo['name'], 'FaceQnet', photo['faceqnet'], flush=True)


def ranking(photos, key, k=5):
    ranked, hashes = [], set()
    for p in sorted((p for p in photos if key in p and p[key] is not None), key=lambda p: (-p[key], p['name'])):
        if p['hash'] not in hashes:
            ranked.append(p)
            hashes.add(p['hash'])
    return ranked[:k]


def render(args):
    from PIL import Image, ImageOps, ImageDraw, ImageFont
    import html
    root, result = args.output, load(args.output)
    photos = result['photos']
    ofiq = sorted((p for p in photos if p['ofiqRank']), key=lambda p: p['ofiqRank'])
    ser, face = ranking(photos, 'serfiq'), ranking(photos, 'faceqnet')
    result['rankings'] = dict(ofiq=[p['id'] for p in ofiq], serfiq=[p['id'] for p in ser], faceqnet=[p['id'] for p in face])
    result['serfiqRuns'] = [[p['id'] for p in ranking([dict(p, run=p['serfiqSamples'][i]) for p in photos if 'serfiq' in p], 'run')] for i in range(3)]
    result['overlap'] = dict(serfiqOfiq=len(set(result['rankings']['serfiq']) & set(result['rankings']['ofiq'])),
                             faceqnetOfiq=len(set(result['rankings']['faceqnet']) & set(result['rankings']['ofiq'])),
                             serfiqFaceqnet=len(set(result['rankings']['serfiq']) & set(result['rankings']['faceqnet'])))
    person = json.load(urllib.request.urlopen(args.api + '/people/' + args.person))
    assert all(sha(Path(p['path'])) == p['fileSha'] for p in photos), '原图内容发生变化'
    assert result['before'] == dict(baselineId=person['baselineId'], lockedPhotoId=person['lockedPhotoId'], history=person['history'])
    result['verified'] = dict(originalFilesUnchanged=True, baselineAndHistoryUnchanged=True)
    save(root, result)

    def data_uri(image, size):
        image = image.copy(); image.thumbnail(size)
        stream = io.BytesIO(); image.save(stream, 'JPEG', quality=88)
        return 'data:image/jpeg;base64,' + base64.b64encode(stream.getvalue()).decode()

    for p in photos:
        with Image.open(root / 'inputs' / (p['id'] + '.png')) as image:
            p['full'] = data_uri(image, (900, 900))
            box = p.get('faceBox')
            p['face'] = data_uri(image.crop(box), (400, 400)) if box else p['full']
        p.pop('path'); p.pop('fileSha')
    payload = json.dumps(result, ensure_ascii=False).replace('<', '\\u003c')
    template = Path(__file__).with_name('fiqa-comparison.html').read_text()
    args.preview.mkdir(parents=True, exist_ok=True)
    (args.preview / 'index.html').write_text(template.replace('/*RESULTS*/null', payload))

    font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    font = ImageFont.truetype(font_path, 24)
    canvas = Image.new('RGB', (1500, 1185), '#f7f7f2')
    draw = ImageDraw.Draw(canvas)
    for row, (label, items, key) in enumerate([('SER-FIQ / 3 runs mean', ser, 'serfiq'), ('FaceQnet v1', face, 'faceqnet'), ('Current OFIQ', ofiq, 'ofiq')]):
        top = row * 395
        draw.text((20, top + 10), label, fill='#1e3831', font=font)
        for column, p in enumerate(items):
            x = column * 300
            with Image.open(root / 'inputs' / (p['id'] + '.png')) as image:
                crop = image.crop(p['faceBox']) if 'faceBox' in p else image
                face_img = ImageOps.contain(crop, (275, 285))
                canvas.paste(face_img, (x + (300-face_img.width)//2, top + 55))
            draw.text((x + 15, top + 345), f"#{column+1}   {p[key]:.4f}" if key != 'ofiq' else f"#{column+1}   {p[key]:.0f}", fill='#1e3831', font=font)
    canvas.save(root / 'top5-comparison.jpg', quality=92)
    print(json.dumps(dict(rankings={k:[next(p['name'] for p in photos if p['id']==i) for i in v] for k,v in result['rankings'].items()}, overlap=result['overlap'], verified=result['verified']), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'serfiq', 'faceqnet', 'render'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--person', default='ee0088ac7ee04b59b5931f16c44b8f39')
    parser.add_argument('--api', default='http://127.0.0.1:33081/api')
    parser.add_argument('--database', default='/vol2/1000/Docker/face-baseline/data/baseline.sqlite')
    parser.add_argument('--ser-source', type=Path, default=Path('/vol1/1000/Code/Others/face-quality-reference/SER-FIQ'))
    parser.add_argument('--preview', type=Path, default=Path('/vol2/1000/Docker/face-baseline/previews/fiqa-xiaoyu'))
    args = parser.parse_args()
    globals()[args.stage](args)
