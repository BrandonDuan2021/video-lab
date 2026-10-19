#!/usr/bin/env python3
"""
第二步：按剪辑表渲染成片
剪辑表 shots.json 由 Claude 看完联系表后写，你也可以手改：
{
  "clips_dir": "~/Desktop/bike_clips",
  "music": "~/Desktop/bike_clips/music.mp3",
  "output": "~/Desktop/bike_vlog.mp4",
  "aspect": "16:9",              // 或 "9:16"
  "beat_snap": true,             // 切点自动吸附到最近的音乐节拍
  "look": "eq=contrast=1.06:saturation=1.12:gamma=0.98",
  "shots": [
    {"file": "GX010001.MP4", "in": 12.0, "len": 3.0, "speed": 1.0, "note": "出发"},
    {"file": "GX010002.MP4", "in": 4.5,  "len": 2.0, "speed": 0.5, "note": "车轮特写慢放"}
  ]
}
len = 成片里这个镜头的秒数；speed 0.5 = 慢放一半（素材要 ≥60fps 才顺滑）

用法：python3 render_edit.py shots.json
依赖：brew install ffmpeg ; pip3 install librosa numpy（beat_snap 才需要 librosa）
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile

IS_MAC = platform.system() == "Darwin"
FPS = 30


def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        print(r.stderr[-1500:])
        sys.exit(f"❌ 命令失败: {' '.join(cmd[:6])} ...")
    return r.stdout


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", path]).strip())


def snap_to_beats(shots, music):
    """把每个切点挪到最近的节拍上，镜头长度跟着微调（最多 ±40%）。"""
    import librosa
    y, sr = librosa.load(music, sr=22050, mono=True)
    _, b = librosa.beat.beat_track(y=y, sr=sr)
    beats = librosa.frames_to_time(b, sr=sr)
    if len(beats) < 4:
        print("⚠️ 节拍不明显，跳过卡点")
        return
    t = 0.0
    for s in shots:
        target = t + s["len"]
        nearest = float(beats[abs(beats - target).argmin()])
        new_len = nearest - t
        if 0.6 * s["len"] <= new_len <= 1.4 * s["len"] and new_len > 0.4:
            s["len"] = round(new_len, 3)
        t += s["len"]


def main():
    if len(sys.argv) < 2:
        sys.exit("用法：python3 render_edit.py shots.json")
    cfg = json.load(open(sys.argv[1]))
    clips = os.path.expanduser(cfg["clips_dir"])
    music = os.path.expanduser(cfg.get("music") or "")
    out = os.path.expanduser(cfg.get("output", "~/Desktop/bike_vlog.mp4"))
    w, h = (1920, 1080) if cfg.get("aspect", "16:9") == "16:9" else (1080, 1920)
    look = cfg.get("look", "eq=contrast=1.06:saturation=1.12:gamma=0.98")
    shots = cfg["shots"]
    has_music = bool(music) and os.path.exists(music)
    if cfg.get("music") and not has_music:
        sys.exit(f"❌ 找不到配乐 {music}")
    if has_music and cfg.get("beat_snap", True):
        snap_to_beats(shots, music)

    encs = run(["ffmpeg", "-hide_banner", "-encoders"])
    enc = (["-c:v", "h264_videotoolbox", "-b:v", "14M"] if "h264_videotoolbox" in encs
           else ["-c:v", "libx264", "-preset", "fast", "-crf", "19"])
    hw = ["-hwaccel", "videotoolbox"] if IS_MAC else []

    tmp = tempfile.mkdtemp(prefix="render_")
    parts, total = [], 0.0
    for i, s in enumerate(shots):
        src = os.path.join(clips, s["file"])
        speed = float(s.get("speed", 1.0))
        src_len = s["len"] * speed
        start = max(0.0, min(float(s["in"]), duration(src) - src_len - 0.05))
        seg = os.path.join(tmp, f"{i:03d}.mp4")
        vf = (f"setpts={1 / speed:.4f}*PTS,fps={FPS},"
              f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
              f"{look},format=yuv420p")
        run(["ffmpeg", "-y", "-v", "error"] + hw +
            ["-ss", f"{start:.3f}", "-t", f"{src_len:.3f}", "-i", src,
             "-vf", vf, "-t", f"{s['len']:.3f}", "-an"] + enc + [seg])
        parts.append(seg)
        total += s["len"]
        print(f"  🎞️ {i + 1}/{len(shots)} {s['file']} @{start:.1f}s {s['len']:.1f}s"
              f"{' 慢放' if speed < 1 else ''}  {s.get('note', '')}")

    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    joined = os.path.join(tmp, "joined.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
         "-c", "copy", joined])

    fo = max(total - 1.5, 0)
    vfade = f"fade=t=in:st=0:d=0.6,fade=t=out:st={fo:.2f}:d=1.5"
    if has_music:
        run(["ffmpeg", "-y", "-v", "error", "-i", joined, "-i", music,
             "-vf", vfade, "-af", f"afade=t=in:st=0:d=0.3,afade=t=out:st={fo:.2f}:d=1.5",
             "-map", "0:v", "-map", "1:a", "-t", f"{total:.3f}"] + enc +
            ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out])
    else:
        run(["ffmpeg", "-y", "-v", "error", "-i", joined, "-vf", vfade] + enc +
            ["-movflags", "+faststart", out])
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n✨ 成片 {total:.1f}s → {out}")


if __name__ == "__main__":
    main()
