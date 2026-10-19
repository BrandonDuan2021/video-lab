"""构图（看关键帧）：
  人脸：OpenCV 自带的 Haar 检测器（离线、无需下载模型；侧脸会漏）
  景别：人脸高度 / 画面高度 → 大特写 / 特写 / 近景 / 中景 / 全景；没人脸 = "无人脸"（交给结论层看图）
  主体位置：人脸中心，没人脸用清晰度重心 → 左三分 / 居中 / 右三分；头顶留白
  景深：主体区域清晰度 / 画面边缘清晰度 → 浅景深 / 深景深
  对称度：画面和它的左右镜像有多像
"""
import os

import cv2
import numpy as np

from ..config import DOF_SHALLOW, SCALE_BINS

_FACE = None


def face_detector():
    """Haar 在 OpenCV 4.x 主包里；5.0 把它挪出去了 → 返回 None，人脸相关字段跳过。"""
    global _FACE
    if _FACE is None:
        if hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data"):
            _FACE = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades,
                                                       "haarcascade_frontalface_default.xml"))
        else:
            _FACE = False
    return _FACE or None


def detect_face(gray):
    det = face_detector()
    if det is None:
        return None, 0
    h = gray.shape[0]
    faces = det.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6,
                                 minSize=(max(24, h // 20),) * 2)
    if len(faces) == 0:
        return None, 0
    x, y, w, hh = max(faces, key=lambda f: f[2] * f[3])
    return (int(x), int(y), int(w), int(hh)), len(faces)


def thirds(x):
    return "左三分" if x < 0.42 else ("右三分" if x > 0.58 else "居中")


def analyze(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    face, nfaces = detect_face(gray)
    sharp = cv2.GaussianBlur(np.abs(cv2.Laplacian(gray.astype(np.float32), cv2.CV_32F)),
                             (0, 0), 3)
    border = np.zeros_like(gray, bool)
    m = int(0.12 * min(H, W))
    border[:m] = border[-m:] = True
    border[:, :m] = border[:, -m:] = True

    out = {"faces": nfaces}
    if face:
        x, y, w, h = face
        ratio = h / H
        out["shot_scale"] = next(lbl for th, lbl in SCALE_BINS if ratio >= th)
        out["face_h_ratio"] = round(ratio, 3)
        out["face_box"] = [x, y, w, h]
        cx, cy = (x + w / 2) / W, (y + h / 2) / H
        out["headroom"] = round(y / H, 3)
        x0, x1 = max(0, x - w // 2), min(W, x + w + w // 2)
        y0, y1 = max(0, y - h // 2), min(H, y + h * 2)
        subj = sharp[y0:y1, x0:x1]
    else:
        out["shot_scale"] = "无人脸"
        tot = sharp.sum() + 1e-6
        cy = float((sharp.sum(1) * np.arange(H)).sum() / tot) / H
        cx = float((sharp.sum(0) * np.arange(W)).sum() / tot) / W
        subj = sharp[H // 4: 3 * H // 4, W // 4: 3 * W // 4]
    out["subject_x"], out["subject_y"] = round(cx, 3), round(cy, 3)
    out["position"] = thirds(cx)
    dof = float(subj.mean() / (sharp[border].mean() + 1e-3))
    out["dof_ratio"] = round(dof, 2)
    out["dof"] = "浅景深" if dof > DOF_SHALLOW else "深景深"
    flip = cv2.flip(gray, 1).astype(np.float32)
    g = gray.astype(np.float32)
    out["symmetry"] = round(float(np.corrcoef(g.ravel(), flip.ravel())[0, 1]), 2)
    return out


def run(ctx):
    if face_detector() is None:
        ctx.skip("人脸 / 景别", f"OpenCV {cv2.__version__} 没有 Haar 检测器"
                 "（pip3 install 'opencv-python<5'）；景别全部记为“无人脸”")
    for s in ctx.shots:
        if not s.get("keyframe"):
            continue
        img = cv2.imread(os.path.join(ctx.run_dir, s["keyframe"]))
        if img is not None:
            s["composition"] = analyze(img)
    return "完成"
