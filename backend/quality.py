import json


POLICY_VERSION = 'baseline-v2'
MINIMUMS = (
    ('Sharpness', 70, '脸部清晰度不足（需 ≥70）'),
    ('InterEyeDistance', 70, '脸部有效像素不足（眼间距需 ≥70px）'),
    ('EyesVisible', 80, '眼睛可见程度不足（需 ≥80）'),
    ('EyesOpen', 70, '眼睛张开程度不足（需 ≥70）'),
    ('FaceOcclusionPrevention', 80, '面部遮挡较多（需 ≥80）'),
    ('HeadPoseYaw', 80, '左右侧脸角度过大（需 ≥80）'),
    ('HeadPosePitch', 80, '抬头或低头角度过大（需 ≥80）'),
    ('HeadPoseRoll', 80, '头部倾斜过大（需 ≥80）'),
    ('IlluminationUniformity', 50, '脸部光照不均匀（需 ≥50）'),
)


def assess(photo, threshold, engine_version):
    metrics = json.loads(photo['metrics'] or '{}')
    if photo['engine'] != engine_version:
        return {'eligible': False, 'qualified': False, 'issues': ['检测规则已升级，等待重新扫描']}
    if photo['status'] != 'ok' or photo['score'] is None:
        return {'eligible': False, 'qualified': False, 'issues': [photo['error'] or '照片无法作为基线']}
    if not metrics.get('FaceValidation', {}).get('matched'):
        return {'eligible': False, 'qualified': False, 'issues': ['评分人脸尚未通过检测复核']}
    issues = []
    if photo['score'] < threshold:
        issues.append(f'OFIQ 总分低于 {threshold}')
    for name, minimum, message in MINIMUMS:
        item = metrics.get(name)
        value = item.get('raw' if name == 'InterEyeDistance' else 'scalar') if item and item['code'] == 0 else None
        if value is None or value < 0:
            issues.append(f'{message.split("（")[0]}未能评估')
        elif value < minimum:
            issues.append(message)
    box = metrics['FaceValidation']['box']
    if min(box[2], box[3]) < 120:
        issues.append('人脸尺寸不足（宽高均需 ≥120px）')
    return {'eligible': True, 'qualified': not issues, 'issues': issues}
