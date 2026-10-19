"""光线和色彩。
  逐帧：亮度、对比度、亮部/暗部分位数、色温（R/B）、饱和度、溢出、中心 vs 边缘亮度、左右 / 上下明暗
  每镜头：上面的平均 + 关键帧色板（k-means 5 色）+ Lab 平均（算全片调色一致性）
  主光方向和光比：有人脸时比较脸的左右半边（在 composition 之后跑）
"""
import os

import cv2
import numpy as np

from ..config import AW, AH
from ..decode import FrameConsumer

_center = np.zeros((AH, AW), bool)
_center[AH // 4: 3 * AH // 4, AW // 4: 3 * AW // 4] = True


class StatsConsumer(FrameConsumer):
    name = "stats"

    def __init__(self):
        self.cols = {k: [] for k in ("luma", "contrast", "p5", "p95", "warmth", "sat",
                                     "clip_hi", "clip_lo", "center_ratio", "lr", "tb")}

    def update(self, i, bgr, gray, small):
        g = gray.astype(np.float32)
        c = self.cols
        c["luma"].append(float(g.mean()))
        c["contrast"].append(float(g.std()))
        p5, p95 = np.percentile(g, [5, 95])
        c["p5"].append(float(p5)); c["p95"].append(float(p95))
        b, _, r = (bgr[..., j].astype(np.float32).mean() for j in range(3))
        c["warmth"].append(float((r + 1) / (b + 1)))
        c["sat"].append(float(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[..., 1].mean()))
        c["clip_hi"].append(float((gray >= 250).mean()))
        c["clip_lo"].append(float((gray <= 5).mean()))
        c["center_ratio"].append(float((g[_center].mean() + 1) / (g[~_center].mean() + 1)))
        c["lr"].append(float((g[:, :AW // 2].mean() + 1) / (g[:, AW // 2:].mean() + 1)))
        c["tb"].append(float((g[:AH // 2].mean() + 1) / (g[AH // 2:].mean() + 1)))

    def result(self):
        return {k: np.array(v, np.float32) for k, v in self.cols.items()}


def palette(img, k=5):
    small = cv2.resize(img, (96, 54)).reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(small, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=k)
    order = np.argsort(-counts)
    return [{"hex": "#%02x%02x%02x" % tuple(int(v) for v in centers[i][::-1]),
             "share": round(float(counts[i] / counts.sum()), 2)} for i in order]


def key_light(img, face):
    """脸的左右半边亮度比 → 主光方向 + 光比。左右以画面为准。"""
    x, y, w, h = face
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    roi = g[y:y + h, x:x + w]
    if roi.size == 0:
        return None
    left, right = roi[:, : w // 2].mean() + 1, roi[:, w // 2:].mean() + 1
    ratio = float(max(left, right) / min(left, right))
    side = "正面平光" if ratio < 1.15 else ("画面左侧" if left > right else "画面右侧")
    return {"key_side": side, "face_light_ratio": round(ratio, 2)}


def run(ctx):
    F = ctx.frames
    for s in ctx.shots:
        sl = ctx.shot_slice(s)
        s["light"] = {k: round(float(F[k][sl].mean()), 3 if k.startswith("clip") else 2)
                      for k in ("luma", "contrast", "p5", "p95", "warmth", "sat",
                                "clip_hi", "clip_lo", "center_ratio", "lr", "tb")}
        img = cv2.imread(os.path.join(ctx.run_dir, s["keyframe"])) if s.get("keyframe") else None
        if img is None:
            continue
        s["palette"] = palette(img)
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32).mean(0)
        s["lab_mean"] = [round(float(v), 1) for v in lab]
        face = (s.get("composition") or {}).get("face_box")
        if face:
            kl = key_light(img, face)
            if kl:
                s["light"].update(kl)
    return "完成"
