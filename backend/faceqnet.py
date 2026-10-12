import hashlib
import json
import os
from pathlib import Path
import struct

import cv2
import numpy as np
import onnxruntime as ort

from .detector import DETECTOR_VERSION, FaceDetector, overlap
from .engine import OfiqEngine
from .mtcnn import MtcnnBoxes


class FaceQnetEngine:
    version = f'FaceQnet-v1-90e86f52/onnx-v1/MTCNN-mxnet-onnx-v1/{OfiqEngine.version}'

    def __init__(self, store):
        self.store = store
        self.directory = Path(os.environ.get('FACEQNET_DATA', '/opt/faceqnet'))
        self.session = self.detector = self.mtcnn = None
        self.diagnostics = OfiqEngine()

    def start(self):
        self.detector = FaceDetector()
        self.mtcnn = MtcnnBoxes(self.directory / 'mtcnn')
        options = ort.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
        self.session = ort.InferenceSession(str(self.directory / 'faceqnet-v1.onnx'), sess_options=options, providers=['CPUExecutionProvider'])

    def score(self, image):
        metrics = {}
        try:
            if self.session is None:
                self.start()
            faces = self.detector.detect(image)
            metrics = dict(Detector=DETECTOR_VERSION, DetectionFaces=faces,
                           DetectedFaces=len(faces), ImageSize=list(image.size), ScoreModel='faceqnet')
            if len(faces) != 1:
                return dict(status='no_face' if not faces else 'multi_face', score=None, metrics=metrics,
                            error='全图复核未检测到人脸' if not faces else f'全图复核检测到 {len(faces)} 张人脸')
            bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
            boxes = self.mtcnn.detect(bgr)
            metrics['MTCNNFaces'] = boxes.tolist()
            if len(boxes) != 1:
                return dict(status='no_face' if not len(boxes) else 'multi_face', score=None, metrics=metrics,
                            error='MTCNN 未检测到人脸' if not len(boxes) else f'MTCNN 复核检测到 {len(boxes)} 张人脸')
            x1, y1 = np.maximum(np.floor(boxes[0, :2]).astype(int), 0)
            x2, y2 = np.minimum(np.ceil(boxes[0, 2:4]).astype(int), image.size)
            box = [int(x1), int(y1), int(x2-x1), int(y2-y1)]
            if overlap(box, faces[0]['box']) < .25:
                return dict(status='face_mismatch', score=None, metrics=metrics, error='两次检测的人脸位置不一致，不能作为基线')
            crop = cv2.resize(bgr[y1:y2, x1:x2], (224, 224)).astype(np.float32)
            raw = float(self.session.run(None, {self.session.get_inputs()[0].name: crop[None]})[0].reshape(-1)[0])
            if not np.isfinite(raw):
                raise ValueError('FaceQnet 返回无效分数')
            score = min(1., max(0., raw)) * 100
            digest = hashlib.sha256(struct.pack('>II', *image.size) + image.tobytes()).hexdigest()
            with self.store.connect() as db:
                cached = db.execute('SELECT result FROM scores WHERE hash=? AND engine=?', (digest, OfiqEngine.version)).fetchone()
            diagnostic = json.loads(cached[0]) if cached else self.diagnostics.score(image)
            if not cached and diagnostic['status'] != 'score_failed':
                with self.store.connect() as db:
                    db.execute('INSERT OR REPLACE INTO scores VALUES(?,?,?)', (digest, OfiqEngine.version, json.dumps(diagnostic)))
            original = diagnostic['metrics']
            metrics = {**original, **metrics}
            metrics['DiagnosticEngine'] = OfiqEngine.version
            metrics['DiagnosticFace'] = original.get('FaceValidation')
            metrics['OFIQUnifiedQualityScore'] = original.get('UnifiedQualityScore')
            metrics['UnifiedQualityScore'] = dict(raw=raw, scalar=score, code=0)
            metrics['FaceValidation'] = dict(matched=True, box=box, crop=[int(x1), int(y1), int(x2), int(y2)])
            if diagnostic.get('error'):
                metrics['DiagnosticError'] = diagnostic['error']
            return dict(status='ok', score=score, metrics=metrics, error=None)
        except (OSError, ValueError, RuntimeError, cv2.error, ort.capi.onnxruntime_pybind11_state.Fail) as exc:
            return dict(status='score_failed', score=None, metrics=metrics, error=f'FaceQnet：{exc}')

    def close(self):
        self.session = self.detector = self.mtcnn = None
        self.diagnostics.close()
