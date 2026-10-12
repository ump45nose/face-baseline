import json
import os
import select
import struct
import subprocess

import cv2

from .detector import DETECTOR_VERSION, FaceDetector, overlap


MEASURES = ['UnifiedQualityScore', 'BackgroundUniformity', 'IlluminationUniformity',
            'LuminanceMean', 'LuminanceVariance', 'UnderExposurePrevention',
            'OverExposurePrevention', 'DynamicRange', 'Sharpness', 'NoCompressionArtifacts',
            'NaturalColour', 'SingleFacePresent', 'EyesOpen', 'MouthClosed', 'EyesVisible',
            'MouthOcclusionPrevention', 'FaceOcclusionPrevention', 'InterEyeDistance',
            'HeadSize', 'LeftwardCropOfTheFaceImage', 'RightwardCropOfTheFaceImage',
            'MarginAboveOfTheFaceImage', 'MarginBelowOfTheFaceImage',
            'HeadPoseYaw', 'HeadPosePitch', 'HeadPoseRoll', 'ExpressionNeutrality', 'NoHeadCoverings']


class OfiqEngine:
    version = f'OFIQ-1.0.3/{DETECTOR_VERSION}/crop-v2'

    def __init__(self):
        self.process = None
        self.detector = None

    def read(self):
        if not select.select([self.process.stdout], [], [], 180)[0]:
            self.close()
            raise RuntimeError('OFIQ 评分超时')
        line = self.process.stdout.readline()
        if not line:
            self.close()
            raise RuntimeError('OFIQ 评分进程退出')
        return json.loads(line)

    def start(self):
        self.process = subprocess.Popen([os.environ.get('OFIQ_RUNNER', '/app/ofiq-runner'),
                                         os.environ.get('OFIQ_DATA', '/opt/ofiq/data')],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        hello = self.read()
        if hello['code'] != 0 or hello['version'] != '1.0.3':
            self.close()
            raise RuntimeError(f'OFIQ 固定版本初始化失败：{hello}')

    def score(self, image):
        try:
            if not self.detector:
                self.detector = FaceDetector()
            faces = self.detector.detect(image)
            inspection = dict(Detector=DETECTOR_VERSION, DetectionFaces=faces,
                              DetectedFaces=len(faces), ImageSize=list(image.size))
            if not faces:
                return dict(status='no_face', score=None, metrics=inspection, error='全图复核未检测到人脸')
            if len(faces) > 1:
                return dict(status='multi_face', score=None, metrics=inspection, error=f'全图复核检测到 {len(faces)} 张人脸')
            if not self.process:
                self.start()
            if max(image.size) > 32767:
                raise ValueError('图像尺寸超过 OFIQ 的 32767 像素限制')
            x, y, w, h = faces[0]['box']
            crop_box = (max(0, round(x - .75 * w)), max(0, round(y - .5 * h)),
                        min(image.width, round(x + 1.75 * w)), min(image.height, round(y + 1.5 * h)))
            face_image = image.crop(crop_box)
            self.process.stdin.write(struct.pack('<II', *face_image.size) + face_image.tobytes())
            self.process.stdin.flush()
            result = self.read()
            metrics = {MEASURES[int(k) - 65]: v for k, v in result['metrics'].items()}
            metrics.update(inspection)
            metrics['OFIQDetectedFaces'] = result['faces']
            metrics['ReturnCode'] = result['code']
            boxes = [[b[0] + crop_box[0], b[1] + crop_box[1], b[2], b[3]] for b in result['boxes']]
            metrics['OFIQFaces'] = boxes
            if result['faces'] > 1:
                status, score, error = 'multi_face', None, f'检测到 {result["faces"]} 张人脸'
            elif result['code'] != 0:
                status, score, error = 'score_failed', None, f'OFIQ 返回错误码 {result["code"]}'
            elif result['faces'] == 0:
                status, score, error = 'score_failed', None, 'OFIQ 未能复核检测到的人脸'
            elif overlap(boxes[0], faces[0]['box']) < .25:
                status, score, error = 'face_mismatch', None, '两次检测的人脸位置不一致，不能作为基线'
            else:
                metrics['FaceValidation'] = dict(matched=True, box=boxes[0], crop=list(crop_box))
                total = metrics['UnifiedQualityScore']
                if total['code'] != 0 or total['scalar'] is None or total['scalar'] < 0:
                    status, score, error = 'score_failed', None, 'OFIQ 无法计算总分'
                else:
                    status, score, error = 'ok', total['scalar'], None
            return dict(status=status, score=score, metrics=metrics, error=error)
        except (OSError, RuntimeError, ValueError, cv2.error) as exc:
            self.close()
            return dict(status='score_failed', score=None, metrics={}, error=str(exc))

    def close(self):
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)
            self.process = None


def engine_for(model, store):
    if model == 'ofiq':
        return OfiqEngine()
    from .faceqnet import FaceQnetEngine
    return FaceQnetEngine(store)
