#!/usr/bin/env python3
"""
第一步：体检素材（不剪，只看）
对每段视频：读参数（分辨率/帧率/编码/时长）→ 生成缩略图联系表 → 逐秒打分（清晰/曝光/抖动）
输出到 <素材文件夹>/_inspect/：
  report.json        所有参数 + 每秒分数（给 Claude 读）
  sheet_<名字>.jpg   每段一张联系表，每格标了秒数（给 Claude 看画面）

用法：python3 inspect_footage.py ~/Desktop/bike_clips
依赖：brew install ffmpeg ; pip3 install opencv-python numpy
"""
import json
import os
import platform
import subprocess
import sys

import cv2
import numpy as np

VIDEO_EXT = (".mp4", ".mov", ".m4v")
IS_MAC = platform.system() == "Darwin"
STEP_S = 1                     # 默认每秒截一帧；20 分钟 = 1200 帧 = 40 张图


def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        print(r.stderr[-1500:])
        sys.exit(f"❌ 命令失败: {' '.join(cmd[:5])} ...")
    return r.stdout


def probe(path):
    info = json.loads(run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate:"
                         "stream_side_data=rotation:format=duration",
        "-of", "json", path]))
    s = info["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    rot = 0
    for sd in s.get("side_data_list", []) or []:
        rot = int(sd.get("rotation", 0) or 0)
    return {"codec": s.get("codec_name"), "width": s.get("width"),
            "height": s.get("height"), "fps": round(float(num) / float(den), 2),
            "rotation": rot, "duration": round(float(info["format"]["duration"]), 2)}


def make_proxy(src, dst):
    """4K 只解码这一次：M3 硬件转 480p 代理，之后打分/截帧/放大都读代理。"""
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return
    hw = ["-hwaccel", "videotoolbox"] if IS_MAC else []
    encs = run(["ffmpeg", "-hide_banner", "-encoders"])
    enc = (["-c:v", "h264_videotoolbox", "-b:v", "1500k"] if "h264_videotoolbox" in encs
           else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"])
    tmp = dst + ".part.mp4"
    run(["ffmpeg", "-y", "-v", "error"] + hw +
        ["-i", src, "-vf", "scale=-2:480,fps=30", "-an"] + enc + [tmp])
    os.replace(tmp, dst)


def contact_sheet(path, out_pattern, step, start=None, end=None):
    """每 step 秒截一帧，每 30 帧（6×5）拼一张图，长视频自动分成多张。
    out_pattern 形如 sheet_GX01_%02d.jpg；start/end 用于放大某一段。"""
    hw = ["-hwaccel", "videotoolbox"] if IS_MAC else []
    seek = []
    if start is not None:
        seek = ["-ss", f"{start:.2f}", "-to", f"{end:.2f}"]
    # 时间标签显示的是原片里的绝对时间
    offset = start or 0
    label = (f"drawtext=text='%{{pts\\:hms\\:{offset:.2f}}}':x=6:y=6:fontsize=18:"
             f"fontcolor=white:box=1:boxcolor=black@0.6,")
    base = f"fps=1/{step:.3f},scale=320:-2,"
    tile = "tile=6x5:padding=4"
    for vf in (base + label + tile, base + tile):   # 没有 drawtext 时退回无标签版
        r = subprocess.run(["ffmpeg", "-y", "-v", "error"] + hw + seek +
                           ["-i", path, "-vf", vf, "-q:v", "4", out_pattern],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if r.returncode == 0:
            return
    print(r.stderr[-1500:])
    sys.exit("❌ 生成联系表失败")


def per_second_scores(path):
    """5fps 低清读帧，每秒汇总一个清晰度/亮度/抖动。"""
    hw = ["-hwaccel", "videotoolbox"] if IS_MAC else []
    proc = subprocess.Popen(["ffmpeg", "-v", "error"] + hw +
                            ["-i", path, "-vf", "fps=5,scale=320:180,format=gray",
                             "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    fsize = 320 * 180
    sharp, bright, shift = [], [], []
    prev = None
    while True:
        buf = proc.stdout.read(fsize)
        if len(buf) < fsize:
            break
        g = np.frombuffer(buf, np.uint8).reshape(180, 320).astype(np.float32)
        sharp.append(float(cv2.Laplacian(g, cv2.CV_32F).var()))
        bright.append(float(g.mean()))
        if prev is not None:
            (dx, dy), _ = cv2.phaseCorrelate(prev, g)
            shift.append((dx, dy))
        else:
            shift.append((0.0, 0.0))
        prev = g
    proc.wait()
    if not sharp:
        return []
    s = np.array(shift)
    jerk = np.zeros(len(s))
    if len(s) > 2:
        jerk[1:-1] = np.linalg.norm(s[2:] - 2 * s[1:-1] + s[:-2], axis=1)
    speed = np.linalg.norm(s, axis=1)
    out = []
    for sec in range(0, len(sharp), 5):
        sl = slice(sec, sec + 5)
        out.append({"t": sec // 5,
                    "sharp": round(float(np.mean(sharp[sl])), 1),
                    "bright": round(float(np.mean(bright[sl])), 1),
                    "motion": round(float(np.mean(speed[sl])), 2),
                    "shake": round(float(np.mean(jerk[sl])), 2)})
    return out


def zoom(args):
    """放大模式：zoom <视频文件> <开始秒> <结束秒> [间隔秒，默认 0.5]"""
    path = os.path.expanduser(args[0])
    t0, t1 = float(args[1]), float(args[2])
    step = float(args[3]) if len(args) > 3 else 0.5
    out_dir = os.path.join(os.path.dirname(path), "_inspect", "zoom")
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    proxy = os.path.join(os.path.dirname(path), "_inspect", f"proxy_{stem}.mp4")
    src = proxy if os.path.exists(proxy) else path   # 有代理就读代理，秒出
    pat = os.path.join(out_dir, f"{stem}_{int(t0)}-{int(t1)}_%02d.jpg")
    contact_sheet(src, pat, step, t0, t1)
    print(f"✅ 放大图在 {out_dir}")


def main():
    if len(sys.argv) >= 5 and sys.argv[1] == "zoom":
        return zoom(sys.argv[2:])
    if len(sys.argv) < 2:
        sys.exit("用法：python3 inspect_footage.py <素材文件夹> [每几秒一帧，默认 5]\n"
                 "      python3 inspect_footage.py zoom <视频> <开始秒> <结束秒> [间隔]")
    folder = os.path.expanduser(sys.argv[1])
    step = float(sys.argv[2]) if len(sys.argv) > 2 else STEP_S
    out_dir = os.path.join(folder, "_inspect")
    os.makedirs(out_dir, exist_ok=True)
    files = sorted(f for f in os.listdir(folder)
                   if f.lower().endswith(VIDEO_EXT) and not f.startswith("."))
    if not files:
        sys.exit(f"❌ {folder} 里没有视频")

    report = {"folder": folder, "clips": []}
    for i, f in enumerate(files, 1):
        path = os.path.join(folder, f)
        meta = probe(path)
        print(f"[{i}/{len(files)}] {f}  {meta['width']}x{meta['height']} "
              f"{meta['fps']}fps {meta['codec']} {meta['duration']}s")
        stem = os.path.splitext(f)[0]
        proxy = os.path.join(out_dir, f"proxy_{stem}.mp4")
        print("    ⏳ 转 480p 代理（硬件加速）...")
        make_proxy(path, proxy)
        print("    ⏳ 截帧 + 打分 ...")
        contact_sheet(proxy, os.path.join(out_dir, f"sheet_{stem}_%02d.jpg"), step)
        sheets = sorted(x for x in os.listdir(out_dir) if x.startswith(f"sheet_{stem}_"))
        meta.update({"file": f, "proxy": os.path.basename(proxy), "sheets": sheets,
                     "sheet_step_s": step, "seconds": per_second_scores(proxy)})
        report["clips"].append(meta)

    with open(os.path.join(out_dir, "report.json"), "w") as fp:
        json.dump(report, fp, ensure_ascii=False, indent=1)
    total = sum(c["duration"] for c in report["clips"])
    print(f"\n✅ {len(files)} 段，共 {total / 60:.1f} 分钟素材。结果在 {out_dir}")
    print("👉 回到 Claude 说一声“素材体检好了”。")


if __name__ == "__main__":
    main()
