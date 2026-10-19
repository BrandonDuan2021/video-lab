"""屏幕文字：Mac 上用 ocrmac（Apple Vision），在每个关键帧上识别。没装 / 非 Mac 就跳过。"""
import os

from ..util import IS_MAC, optional


def run(ctx):
    if ctx.opts.get("no_ocr"):
        ctx.skip("屏幕文字", "--no-ocr")
        return "跳过"
    if not IS_MAC:
        ctx.skip("屏幕文字", "只支持 Mac（Apple Vision）")
        return "跳过"
    mod = optional("ocrmac.ocrmac")
    if mod is None:
        ctx.skip("屏幕文字", "没装 ocrmac（pip3 install ocrmac）")
        return "跳过"
    n = 0
    for s in ctx.shots:
        if not s.get("keyframe"):
            continue
        try:
            ann = mod.OCR(os.path.join(ctx.run_dir, s["keyframe"])).recognize()
        except Exception as e:
            ctx.skip("屏幕文字", f"ocrmac 出错：{e}")
            return "失败"
        texts = [t for t, conf, _ in ann if conf >= 0.5 and len(t.strip()) > 1]
        if texts:
            s["text"] = texts
            ctx.timeline.add("text", s["start"], s["end"], text=" | ".join(texts)[:200])
            n += 1
    return f"{n} 个镜头有字"
