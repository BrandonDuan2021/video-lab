"""流水线编排：fetch → 单次解码（帧消费者）→ 各提取步骤 → 融合 → 输出。"""
import os
import time

from . import fuse, report
from .decode import frame_pass
from .extract import STEPS, frame_consumers
from .fetch import fetch
from .model import Context
from .util import log, probe


def _step(name, fn, ctx):
    t0 = time.time()
    log(f"▶ {name} ...")
    msg = fn(ctx)
    log(f"   ✓ {msg or ''}  ({time.time() - t0:.1f}s)")


def run(src, out="runs", **opts):
    ctx = Context(src=src, opts=opts)
    ctx.path, ctx.run_dir, ctx.info = fetch(src, out)
    os.makedirs(ctx.run_dir, exist_ok=True)
    ctx.meta = probe(ctx.path)
    log(f"🎬 {ctx.info.get('title') or os.path.basename(ctx.path)}  "
        f"{ctx.meta['width']}x{ctx.meta['height']} {ctx.meta['fps']}fps "
        f"{ctx.meta['duration'] / 60:.1f}min")

    _step("解码 + 逐帧测量", lambda c: setattr(c, "frames", frame_pass(c.path, frame_consumers()))
          or f"{len(c.frames['luma'])} 帧", ctx)
    for name, mod in STEPS:
        _step(name, mod.run, ctx)
    _step("融合", fuse.run, ctx)
    _step("输出", lambda c: report.write(c) or c.run_dir, ctx)
    return ctx
