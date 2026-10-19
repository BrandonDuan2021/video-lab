"""两种核心数据：
  镜头表 shots：每个镜头一个 dict，提取器往里加字段（motion / light / composition ...）
  事件时间轴 Timeline：带时间戳的事件（word / beat / sfx / text ...），融合层按时间窗查询
Context 把它们和路径、参数装在一起，在流水线里传递。
"""
from dataclasses import dataclass, field

import numpy as np


class Timeline:
    def __init__(self):
        self.events = []

    def add(self, kind, t, end=None, **data):
        self.events.append({"kind": kind, "t": round(float(t), 3),
                            "end": None if end is None else round(float(end), 3), **data})

    def of(self, kind):
        return [e for e in self.events if e["kind"] == kind]

    def times(self, kind):
        return np.array([e["t"] for e in self.events if e["kind"] == kind], np.float32)

    def near(self, kind, t, before, after):
        ts = self.times(kind)
        return bool(len(ts)) and bool(np.any((ts >= t - before) & (ts <= t + after)))

    def covering(self, kind, t, margin=0.0):
        """哪些区间事件（有 end）覆盖了时刻 t。"""
        return [e for e in self.of(kind)
                if e["end"] is not None and e["t"] + margin < t < e["end"] - margin]

    def kinds(self):
        out = {}
        for e in self.events:
            out[e["kind"]] = out.get(e["kind"], 0) + 1
        return out


@dataclass
class Context:
    src: str
    path: str = ""
    run_dir: str = ""
    info: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    opts: dict = field(default_factory=dict)
    frames: dict = field(default_factory=dict)    # 逐帧数组（来自单次解码）
    shots: list = field(default_factory=list)
    timeline: Timeline = field(default_factory=Timeline)
    audio: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    skipped: list = field(default_factory=list)

    def skip(self, step, reason):
        self.skipped.append({"step": step, "reason": reason})
        print(f"   ⚠️  跳过 {step}：{reason}", flush=True)

    @property
    def cuts(self):
        return [s["start"] for s in self.shots[1:]]

    def shot_slice(self, s, pad=1):
        """镜头在逐帧数组里的下标范围（去掉切点附近的帧）。"""
        from .config import AFPS
        n = len(next(iter(self.frames.values()))) if self.frames else 0
        a = min(int(s["start"] * AFPS) + pad, max(n - 1, 0))
        b = min(max(a + 1, int(s["end"] * AFPS) - pad), n)
        return slice(a, b)
