"""每个镜头取中间一帧（640 宽）存盘，后面的构图 / 色板 / OCR / 联系表都用它。"""
import os

import cv2

from ..config import KEYFRAME_W
from ..util import grab_frame


def run(ctx):
    kdir = os.path.join(ctx.run_dir, "keyframes")
    os.makedirs(kdir, exist_ok=True)
    for s in ctx.shots:
        out = os.path.join(kdir, f"{s['idx']:04d}.jpg")
        if not os.path.exists(out):
            img = grab_frame(ctx.path, s["start"] + s["len"] / 2, KEYFRAME_W)
            if img is None:
                continue
            cv2.imwrite(out, img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        s["keyframe"] = os.path.relpath(out, ctx.run_dir)
    return f"{len(ctx.shots)} 张"
