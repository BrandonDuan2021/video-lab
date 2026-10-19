"""切镜头。优先 PySceneDetect（AdaptiveDetector），没装就用内置的同原理算法：
相邻帧 HSV 差 → 和前后几帧的平均比 → 突然高出几倍就是切点。"""
import cv2
import numpy as np

from ..config import AFPS, BUILTIN_CUT_MIN, BUILTIN_CUT_RATIO, FW, FH, MIN_SHOT_S
from ..decode import FrameConsumer
from ..util import optional


class DiffConsumer(FrameConsumer):
    """相邻帧 HSV 平均差（内置切镜头 + 转场分类都用它）。"""
    name = "diff"

    def __init__(self):
        self.prev = None
        self.diff = []

    def update(self, i, bgr, gray, small):
        hsv = cv2.cvtColor(cv2.resize(bgr, (FW, FH)), cv2.COLOR_BGR2HSV).astype(np.int16)
        if self.prev is None:
            self.diff.append(0.0)
        else:
            self.diff.append(float(np.abs(hsv - self.prev).mean()))
        self.prev = hsv

    def result(self):
        return {"hsv_diff": np.array(self.diff, np.float32)}


def _quiet_base(x, i, w=4):
    """前后两侧中较安静那一侧的平均：切点只要比其中一侧突出就算（切点后运动变快也不影响）。"""
    b, a = x[max(1, i - w):i], x[i + 1:i + 1 + w]
    sides = [float(v.mean()) for v in (b, a) if len(v)]
    return min(sides) if sides else 0.0


def builtin_cuts(diff):
    cuts, last = [], -10 ** 9
    for i in range(1, len(diff)):
        if diff[i] >= BUILTIN_CUT_MIN and diff[i] > BUILTIN_CUT_RATIO * (_quiet_base(diff, i) + 1.0) \
                and i - last >= int(MIN_SHOT_S * AFPS):
            cuts.append(i / AFPS)
            last = i
    return cuts


def motion_cuts(F):
    """光流突变：切点前后两帧对不上 → 光流一致性（spread）和幅度同时尖峰。
    专门补帧差法会漏的推镜 / 跳切（画面内容、颜色几乎不变）。"""
    sp, mag, diff = F["spread"], F["mag"], F["hsv_diff"]
    out = []
    for i in range(2, len(sp) - 1):
        if sp[i] > 0.5 and sp[i] > 5 * (_quiet_base(sp, i) + 0.05) \
                and mag[i] > 2 * (_quiet_base(mag, i) + 0.1) \
                and diff[i] > 1.5 * (_quiet_base(diff, i) + 1.0):
            out.append(i / AFPS)
    return out


def merge(cuts, extra, tol=0.3):
    merged = sorted(cuts)
    added = []
    for t in extra:
        if all(abs(t - c) > tol for c in merged):
            merged.append(t)
            added.append(t)
    return sorted(merged), added


def spans_from(cuts, duration):
    bounds = [0.0] + [c for c in sorted(cuts) if 0.05 < c < duration - 0.05] + [duration]
    return [(bounds[k], bounds[k + 1]) for k in range(len(bounds) - 1)
            if bounds[k + 1] - bounds[k] > 0.05]


def run(ctx):
    sd = optional("scenedetect")
    dur = ctx.meta["duration"]
    if sd is not None and not ctx.opts.get("builtin_shots"):
        from scenedetect import detect, AdaptiveDetector
        scenes = detect(ctx.path, AdaptiveDetector(min_scene_len=6), show_progress=False)
        base = [s.get_seconds() for s, _ in scenes][1:]
        backend = "pyscenedetect"
    else:
        base = builtin_cuts(ctx.frames["hsv_diff"])
        backend = "builtin"
    cuts, added = merge(base, motion_cuts(ctx.frames))
    added = set(round(t, 3) for t in added)
    ctx.shots = [{"idx": i, "start": round(a, 3), "end": round(b, 3), "len": round(b - a, 3),
                  "detected_by": "motion" if round(a, 3) in added else backend}
                 for i, (a, b) in enumerate(spans_from(cuts, dur))]
    ctx.info["shot_backend"] = backend
    return f"{len(ctx.shots)} 个镜头（{backend}，光流补检 +{len(added)}）"
