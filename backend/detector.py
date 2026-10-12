import os

import cv2
import numpy as np


DETECTOR_VERSION = 'YuNet-2023mar-8f2383e4/ms1280-c060-i030'


def overlap(a, b):
    x = max(a[0], b[0]); y = max(a[1], b[1])
    width = max(0, min(a[0] + a[2], b[0] + b[2]) - x)
    height = max(0, min(a[1] + a[3], b[1] + b[3]) - y)
    intersection = width * height
    return intersection / (a[2] * a[3] + b[2] * b[3] - intersection)


class FaceDetector:
    def __init__(self):
        cv2.setNumThreads(2)
        self.model = cv2.FaceDetectorYN.create(
            os.environ.get('FACE_BASELINE_DETECTOR', '/opt/ofiq/yunet/face_detection_yunet_2023mar.onnx'),
            '', (320, 320), 0.6, 0.3, 5000)

    def detect(self, image):
        source = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
        width, height = image.size
        found = []
        sizes = set()
        for target in (640, 1280):
            scale = min(1.0, target / max(width, height))
            size = (round(width * scale), round(height * scale))
            if size in sizes:
                continue
            sizes.add(size)
            resized = cv2.resize(source, size) if size != image.size else source
            self.model.setInputSize(size)
            _, faces = self.model.detect(resized)
            for face in faces if faces is not None else []:
                box = [float(v) / scale for v in face[:4]]
                landmarks = [float(v) / scale for v in face[4:14]]
                found.append({'box': box, 'landmarks': landmarks, 'confidence': float(face[14])})
        selected = []
        for face in sorted(found, key=lambda f: -f['confidence']):
            if not any(overlap(face['box'], f['box']) >= 0.3 for f in selected):
                selected.append(face)
        return selected
