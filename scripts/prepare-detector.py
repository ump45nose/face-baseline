#!/usr/bin/env python3
"""Download the pinned OpenCV Zoo YuNet model outside the source tree."""
import argparse
import hashlib
import urllib.request
from pathlib import Path

COMMIT = '47534e27c9851bb1128ccc0102f1145e27f23f98'
SHA256 = '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    directory = parser.parse_args().directory
    directory.mkdir(parents=True, exist_ok=True)
    model = directory / 'face_detection_yunet_2023mar.onnx'
    if not model.exists():
        url = f'https://media.githubusercontent.com/media/opencv/opencv_zoo/{COMMIT}/models/face_detection_yunet/{model.name}'
        urllib.request.urlretrieve(url, model)
    if hashlib.sha256(model.read_bytes()).hexdigest() != SHA256:
        raise SystemExit('YuNet 模型校验失败')
    urllib.request.urlretrieve(f'https://raw.githubusercontent.com/opencv/opencv_zoo/{COMMIT}/models/face_detection_yunet/LICENSE', directory / 'LICENSE')
    print('Pinned YuNet model verified:', model)


if __name__ == '__main__':
    main()
