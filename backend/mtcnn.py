"""MTCNN box pipeline from InsightFace, using its MXNet weights as ONNX.

Adapted from deepinsight/insightface (MIT), as pinned in the SER-FIQ experiment.
The landmark refinement stage does not change boxes and is not needed here.
"""
import math
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort


def nms(boxes, threshold, minimum=False):
    x1, y1, x2, y2, score = boxes[:, :5].T
    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    order, picked = np.argsort(score), []
    while order.size:
        i, rest = order[-1], order[:-1]
        picked.append(i)
        w = np.maximum(0, np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]) + 1)
        h = np.maximum(0, np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]) + 1)
        intersection = w * h
        denominator = np.minimum(area[i], area[rest]) if minimum else area[i] + area[rest] - intersection
        order = rest[intersection / denominator <= threshold]
    return picked


def adjust(image):
    return (image.astype(np.float32).transpose(2, 0, 1)[None] - 127.5) * .0078125


def square(boxes):
    boxes = boxes.copy()
    w, h = boxes[:, 2] - boxes[:, 0] + 1, boxes[:, 3] - boxes[:, 1] + 1
    side = np.maximum(w, h)
    boxes[:, 0] += (w - side) * .5
    boxes[:, 1] += (h - side) * .5
    boxes[:, 2:4] = boxes[:, :2] + side[:, None] - 1
    boxes[:, :4] = np.round(boxes[:, :4])
    return boxes


def calibrate(boxes, regression):
    w, h = boxes[:, 2] - boxes[:, 0] + 1, boxes[:, 3] - boxes[:, 1] + 1
    boxes[:, :4] += np.column_stack([w, h, w, h]) * regression
    return boxes


def patches(image, boxes, size, dtype):
    height, width = image.shape[:2]
    batch = np.empty((len(boxes), 3, size, size), dtype=np.float32)
    for i, b in enumerate(boxes):
        x1, y1, x2, y2 = b[:4].astype(int)
        patch = np.zeros((y2 - y1 + 1, x2 - x1 + 1, 3), dtype=dtype)
        sx, sy, ex, ey = max(0, x1), max(0, y1), min(width - 1, x2), min(height - 1, y2)
        patch[sy-y1:ey-y1+1, sx-x1:ex-x1+1] = image[sy:ey+1, sx:ex+1]
        batch[i] = adjust(cv2.resize(patch, (size, size)))[0]
        # The original pipeline clips the boxes in place before refinement.
        boxes[i, :4] = sx, sy, ex, ey
    return batch


class MtcnnBoxes:
    def __init__(self, directory):
        directory = Path(directory)
        options = ort.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
        self.nets = [ort.InferenceSession(str(directory / f'det{i}.onnx'), sess_options=options,
                                         providers=['CPUExecutionProvider']) for i in (1, 2, 3)]

    @staticmethod
    def forward(net, batch):
        return net.run(None, {net.get_inputs()[0].name: batch})

    def forward_patches(self, net, batch):
        outputs = [[] for _ in net.get_outputs()]
        for start in range(0, len(batch), 64):
            for values, result in zip(outputs, self.forward(net, batch[start:start+64])):
                values.append(result)
        return [np.concatenate(values) for values in outputs]

    def proposals(self, image, scale):
        # PNet has a 12px receptive field and stride 2. Overlap tiles by
        # 10px so each output sees exactly the same pixels as the full image.
        height, width = image.shape[:2]
        boxes = []
        for top in range(0, height-10, 512):
            for left in range(0, width-10, 512):
                tile = image[top:top+522, left:left+522]
                reg, probability = self.forward(self.nets[0], adjust(tile))
                y, x = np.where(probability[0, 1] > .6)
                if len(x):
                    gx, gy = x + left//2, y + top//2
                    boxes.append(np.column_stack([np.round((2*gx+1)/scale), np.round((2*gy+1)/scale),
                                 np.round((2*gx+13)/scale), np.round((2*gy+13)/scale),
                                 probability[0, 1, y, x], reg[0, :, y, x]]))
        if not boxes:
            return np.empty((0, 9))
        boxes = np.vstack(boxes)
        return boxes[nms(boxes, .5)]

    def detect(self, image):
        height, width = image.shape[:2]
        shortest, proposals, scales = min(height, width) * .6, [], []
        count = 0
        while shortest > 12:
            scales.append(.6 * .709 ** count)
            shortest *= .709
            count += 1
        _, rnet, onet = self.nets
        for scale in scales:
            resized = cv2.resize(image, (math.ceil(width * scale), math.ceil(height * scale)))
            boxes = self.proposals(resized, scale)
            if len(boxes):
                proposals.append(boxes)
        if not proposals:
            return np.empty((0, 5))
        boxes = np.vstack(proposals)
        boxes = boxes[nms(boxes, .7)]
        boxes = square(calibrate(boxes[:, :5].copy(), boxes[:, 5:9]))
        reg, probability = self.forward_patches(rnet, patches(image, boxes, 24, np.uint8))
        passed = probability[:, 1] > .7
        boxes, reg = boxes[passed], reg[passed]
        if not len(boxes):
            return boxes
        boxes[:, 4] = probability[passed, 1]
        selected = nms(boxes, .7)
        boxes = square(calibrate(boxes[selected], reg[selected]))
        _, reg, probability = self.forward_patches(onet, patches(image, boxes, 48, np.float32))
        passed = probability[:, 1] > .8
        boxes, reg = boxes[passed], reg[passed]
        if not len(boxes):
            return boxes
        boxes[:, 4] = probability[passed, 1]
        boxes = calibrate(boxes, reg)
        return boxes[nms(boxes, .7, minimum=True)]
