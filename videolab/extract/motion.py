"""运镜。逐帧光流 → 每个镜头：
  类型：固定 / 横移 / 纵移俯仰 / 推近 / 拉远 / 手持晃动
  速度：每秒移动画面宽度的百分之几
  缓入缓出：镜头首尾 20% 的速度 vs 中段
  视差：画面各区域运动是否一致（一致 = 摇镜头；不一致 = 滑轨 / 推轨，有景深层次）
  滚转：旋转分量
"""
import cv2
import numpy as np

from ..config import (AFPS, EASE_RATIO, FW, FH, MOTION_JITTER, MOTION_STATIC,
                      MOTION_ZOOM, PARALLAX_INDEX)
from ..decode import FrameConsumer

_yy, _xx = np.mgrid[0:FH, 0:FW].astype(np.float32)
_rx, _ry = _xx - FW / 2, _yy - FH / 2
_rn = np.sqrt(_rx ** 2 + _ry ** 2) + 1e-6
_rx, _ry = _rx / _rn, _ry / _rn


class FlowConsumer(FrameConsumer):
    name = "flow"

    def __init__(self):
        self.prev = None
        self.cols = {k: [] for k in ("dx", "dy", "div", "curl", "mag", "spread")}

    def update(self, i, bgr, gray, small):
        if self.prev is None:
            for v in self.cols.values():
                v.append(0.0)
        else:
            f = cv2.calcOpticalFlowFarneback(self.prev, small, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            fx, fy = f[..., 0], f[..., 1]
            self.cols["dx"].append(float(np.median(fx)))
            self.cols["dy"].append(float(np.median(fy)))
            self.cols["div"].append(float(np.mean(fx * _rx + fy * _ry)))
            self.cols["curl"].append(float(np.mean(fy * _rx - fx * _ry)))
            self.cols["mag"].append(float(np.mean(np.hypot(fx, fy))))
            cells = [np.median(fx[r:r + FH // 4, c:c + FW // 4])
                     for r in range(0, FH, FH // 4) for c in range(0, FW, FW // 4)]
            self.cols["spread"].append(float(np.std(cells)))
        self.prev = small

    def result(self):
        return {k: np.array(v, np.float32) for k, v in self.cols.items()}


def classify(dx, dy, div):
    mdx, mdy, mdiv = float(np.mean(dx)), float(np.mean(dy)), float(np.mean(div))
    speed = float(np.hypot(mdx, mdy))
    jitter = float(np.mean(np.hypot(np.diff(dx), np.diff(dy)))) if len(dx) > 1 else 0.0
    if jitter > MOTION_JITTER and jitter > 1.5 * speed:
        return "手持晃动", speed, jitter
    if abs(mdiv) > MOTION_ZOOM and abs(mdiv) > 0.5 * speed:
        return ("推近" if mdiv > 0 else "拉远"), speed, jitter
    if speed < MOTION_STATIC:
        return "固定", speed, jitter
    return ("横移" if abs(mdx) >= abs(mdy) else "纵移/俯仰"), speed, jitter


def ease(series):
    n = len(series)
    if n < 8:
        return None, None
    q = max(1, n // 5)
    a, m, b = series[:q].mean(), series[q:n - q].mean(), series[n - q:].mean()
    if m <= 1e-3:
        return None, None
    return bool(a < EASE_RATIO * m), bool(b < EASE_RATIO * m)


def run(ctx):
    F = ctx.frames
    for s in ctx.shots:
        sl = ctx.shot_slice(s)
        dx, dy, div = F["dx"][sl], F["dy"][sl], F["div"][sl]
        if len(dx) < 3:
            s["motion"] = {"type": "固定", "note": "镜头太短"}
            continue
        kind, speed, jitter = classify(dx, dy, div)
        out = {"type": kind,
               "speed_pct_per_s": round(speed * AFPS / FW * 100, 1),
               "zoom": round(float(np.mean(div)), 3),
               "roll": round(float(np.mean(F["curl"][sl])), 3),
               "jitter": round(jitter, 3)}
        if kind != "固定" and kind != "手持晃动":
            ser = np.hypot(dx, dy) if kind in ("横移", "纵移/俯仰") else np.abs(div)
            ei, eo = ease(ser)
            out["ease_in"], out["ease_out"] = ei, eo
        if kind in ("横移", "纵移/俯仰"):
            pidx = float(np.mean(F["spread"][sl]) / (speed + 0.05))
            out["parallax_index"] = round(pidx, 2)
            out["parallax"] = "有视差(滑轨/推轨)" if pidx > PARALLAX_INDEX else "无视差(摇镜)"
        s["motion"] = out
    return "完成"
