#!/usr/bin/env python3
"""
video-lab 测量层入口（facade）
  python3 analyze.py <YouTube 链接 | 本地视频> [--no-asr] [--no-stems] [--no-ocr] [--out runs]

输出 runs/<名字>/：evidence.json、report.md、sheets/、keyframes/、rhythm.png
结论层见 docs/CONCLUSIONS.md。
"""
import argparse
import shutil
import sys

from videolab import pipeline


def main():
    ap = argparse.ArgumentParser(description="video-lab：视频测量层")
    ap.add_argument("src", help="YouTube 链接或本地视频路径")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--no-asr", action="store_true", help="跳过语音转录（纯音乐视频）")
    ap.add_argument("--no-stems", action="store_true", help="跳过 demucs 分轨（快很多）")
    ap.add_argument("--no-ocr", action="store_true", help="跳过屏幕文字识别")
    ap.add_argument("--builtin-shots", action="store_true",
                    help="强制用内置切镜头算法，不用 PySceneDetect")
    a = ap.parse_args()
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit("❌ 需要 ffmpeg：brew install ffmpeg")
    ctx = pipeline.run(a.src, a.out, no_asr=a.no_asr, no_stems=a.no_stems,
                       no_ocr=a.no_ocr, builtin_shots=a.builtin_shots)
    s = ctx.summary
    print(f"\n✅ 完成 → {ctx.run_dir}")
    print(f"   {s['shots']} 个镜头，平均 {s['shot_len']['mean']}s，每分钟 {s['cuts_per_min']} 刀")
    print(f"   切法：{s['cut_kinds']}")
    print(f"   切点对齐：{ {k: v for k, v in s['cut_alignment'].items() if v is not None} }")
    if ctx.skipped:
        print(f"   ⚠️  跳过了 {len(ctx.skipped)} 步，见 report.md")
    print("👉 把这个文件夹交给 Claude，按 docs/CONCLUSIONS.md 出反向结论。")


if __name__ == "__main__":
    main()
