import io
from types import SimpleNamespace

from PIL import Image

from backend.engine import OfiqEngine


class Detector:
    def __init__(self, boxes):
        self.boxes = boxes

    def detect(self, image):
        return [dict(box=b, landmarks=[], confidence=.99) for b in self.boxes]


def test_global_multi_face_detection_blocks_native_scoring():
    engine = OfiqEngine()
    engine.detector = Detector([[20, 20, 100, 150], [200, 20, 100, 150]])
    result = engine.score(Image.new('RGB', (400, 400)))
    assert result['status'] == 'multi_face'
    assert result['metrics']['DetectedFaces'] == 2
    assert engine.process is None


def test_native_face_must_match_global_detection():
    engine = OfiqEngine()
    engine.detector = Detector([[100, 100, 100, 100]])
    engine.process = SimpleNamespace(stdin=io.BytesIO())
    # The crop origin is (25, 50); this native result belongs to another area.
    engine.read = lambda: dict(code=0, faces=1, boxes=[[200, 100, 20, 20]], metrics={'65': dict(raw=30, scalar=94, code=0)})
    result = engine.score(Image.new('RGB', (400, 400)))
    assert result['status'] == 'face_mismatch' and result['score'] is None
    assert 'FaceValidation' not in result['metrics']


def test_assessment_box_returns_to_original_image_coordinates():
    engine = OfiqEngine()
    engine.detector = Detector([[100, 100, 100, 100]])
    engine.process = SimpleNamespace(stdin=io.BytesIO())
    engine.read = lambda: dict(code=0, faces=1, boxes=[[75, 50, 100, 100]], metrics={'65': dict(raw=30, scalar=94, code=0)})
    result = engine.score(Image.new('RGB', (400, 400)))
    assert result['status'] == 'ok'
    assert result['metrics']['FaceValidation']['box'] == [100, 100, 100, 100]
    assert result['metrics']['ImageSize'] == [400, 400]
