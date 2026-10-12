import json
import os
import select
import struct
import subprocess


MEASURES = ['UnifiedQualityScore', 'BackgroundUniformity', 'IlluminationUniformity',
            'LuminanceMean', 'LuminanceVariance', 'UnderExposurePrevention',
            'OverExposurePrevention', 'DynamicRange', 'Sharpness', 'NoCompressionArtifacts',
            'NaturalColour', 'SingleFacePresent', 'EyesOpen', 'MouthClosed', 'EyesVisible',
            'MouthOcclusionPrevention', 'FaceOcclusionPrevention', 'InterEyeDistance',
            'HeadSize', 'LeftwardCropOfTheFaceImage', 'RightwardCropOfTheFaceImage',
            'MarginAboveOfTheFaceImage', 'MarginBelowOfTheFaceImage',
            'HeadPoseYaw', 'HeadPosePitch', 'HeadPoseRoll', 'ExpressionNeutrality', 'NoHeadCoverings']


class OfiqEngine:
    version = 'OFIQ-1.0.3/eu-LISA/rgb-v1'

    def __init__(self):
        self.process = None

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
            if not self.process:
                self.start()
            if max(image.size) > 32767:
                raise ValueError('图像尺寸超过 OFIQ 的 32767 像素限制')
            self.process.stdin.write(struct.pack('<II', *image.size) + image.tobytes())
            self.process.stdin.flush()
            result = self.read()
            metrics = {MEASURES[int(k) - 65]: v for k, v in result['metrics'].items()}
            metrics['DetectedFaces'] = result['faces']
            metrics['ReturnCode'] = result['code']
            # Exact detector count; SingleFacePresent scalar may round a tiny second face to 100.
            if result['code'] == 5:
                status, score, error = 'no_face', None, '未检测到人脸'
            elif result['faces'] > 1:
                status, score, error = 'multi_face', None, f'检测到 {result["faces"]} 张人脸'
            elif result['code'] != 0:
                status, score, error = 'score_failed', None, f'OFIQ 返回错误码 {result["code"]}'
            elif result['faces'] == 0:
                status, score, error = 'no_face', None, '未检测到人脸'
            else:
                total = metrics['UnifiedQualityScore']
                if total['code'] != 0 or total['scalar'] is None or total['scalar'] < 0:
                    status, score, error = 'score_failed', None, 'OFIQ 无法计算总分'
                else:
                    status, score, error = 'ok', total['scalar'], None
            return dict(status=status, score=score, metrics=metrics, error=error)
        except (OSError, RuntimeError, ValueError) as exc:
            self.close()
            return dict(status='score_failed', score=None, metrics={}, error=str(exc))

    def close(self):
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)
            self.process = None
