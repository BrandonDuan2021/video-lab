#!/usr/bin/env python3
"""
video-lab 测量层：把一条视频拆成“证据”
  python3 analyze.py <YouTube 链接 | 本地视频> [--no-asr] [--out runs]

输出 runs/<名字>/
  evidence.json   全部测量结果（镜头、运镜、光线、语音、节拍、切点对齐、汇总）
  sheets/*.jpg    每个镜头的关键帧联系表（带编号/时间/时长），给结论层看
  rhythm.png      节奏曲线（每 10 秒切几刀 + 每个镜头时长）
结论层见 docs/CONCLUSIONS.md：把 evidence.json + sheets 交给 Claude 出“反向结论”。
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys

import cv2
import numpy as np

IS_MAC = platform.system() == "Darwin"
AW, AH = 320, 180          # 分析分辨率
AFPS = 10                  # 分析帧率
SHEET_COLS, SHEET_ROWS = 5, 4
TILE_W, TILE_H = 384, 216


# ---------------------------------------------------------------- utils
def run(cmd, check=True):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and r.returncode != 0:
        print(r.stderr[-1500:])
        sys.exit(f"❌ 命令失败: {' '.join(map(str, cmd[:6]))} ...")
    return r.stdout


def log(msg):
    print(msg, flush=True)


def slugify(s):
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE).strip("_")
    return s[:60] or "video"


# ---------------------------------------------------------------- ① 获取
def fetch(src, out_root):
    if os.path.exists(os.path.expanduser(src)):
        path = os.path.abspath(os.path.expanduser(src))
        name = slugify(os.path.splitext(os.path.basename(path))[0])
        return path, os.path.join(out_root, name), {"source": path}
    if not shutil.which("yt-dlp"):
        sys.exit("❌ 需要 yt-dlp：brew install yt-dlp")
    meta = json.loads(run(["yt-dlp", "-J", "--no-playlist", src]))
    name = slugify(f"{meta.get('uploader', '')}_{meta.get('title', meta.get('id'))}")
    run_dir = os.path.join(out_root, name)
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, "source.mp4")
    if not os.path.exists(path):
        log("⬇️  下载 720p ...")
        run(["yt-dlp", "--no-playlist", "-f",
             "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]/b",
             "--merge-output-format", "mp4", "-o", path, src])
    info = {"source": src, "title": meta.get("title"), "uploader": meta.get("uploader"),
            "upload_date": meta.get("upload_date"), "duration": meta.get("duration")}
    return path, run_dir, info


def probe(path):
    info = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                           "-of", "json", path]))
    s = info["streams"][0]
    n, d = s["r_frame_rate"].split("/")
    return {"width": s["width"], "height": s["height"],
            "fps": round(float(n) / float(d), 3),
            "duration": round(float(info["format"]["duration"]), 3)}


# ---------------------------------------------------------------- ② 切镜头
def detect_shots(path, duration):
    try:
        from scenedetect import detect, AdaptiveDetector
    except ImportError:
        sys.exit("❌ 需要 PySceneDetect：pip3 install 'scenedetect[opencv]'")
    scenes = detect(path, AdaptiveDetector(min_scene_len=6), show_progress=False)
    shots = [(s.get_seconds(), e.get_seconds()) for s, e in scenes]
    if not shots:
        shots = [(0.0, duration)]
    return [{"idx": i, "start": round(a, 3), "end": round(b, 3), "len": round(b - a, 3)}
            for i, (a, b) in enumerate(shots)]


# ---------------------------------------------------------------- ③ 逐帧测量（只解码一次）
def frame_features(path):
    hw = ["-hwaccel", "videotoolbox"] if IS_MAC else []
    proc = subprocess.Popen(["ffmpeg", "-v", "error"] + hw +
                            ["-i", path, "-vf", f"fps={AFPS},scale={AW}:{AH}",
                             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                            stdout=subprocess.PIPE)
    fsize = AW * AH * 3
    yy, xx = np.mgrid[0:AH // 2, 0:AW // 2].astype(np.float32)
    cx, cy = AW / 4, AH / 4
    rx, ry = xx - cx, yy - cy
    rn = np.sqrt(rx ** 2 + ry ** 2) + 1e-6
    rx, ry = rx / rn, ry / rn
    center = np.zeros((AH, AW), bool)
    center[AH // 4: 3 * AH // 4, AW // 4: 3 * AW // 4] = True

    feats = {k: [] for k in ("dx", "dy", "div", "luma", "contrast", "center_ratio",
                             "warmth", "sat", "clip_hi", "clip_lo")}
    prev = None
    while True:
        buf = proc.stdout.read(fsize)
        if len(buf) < fsize:
            break
        bgr = np.frombuffer(buf, np.uint8).reshape(AH, AW, 3)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (AW // 2, AH // 2))
        if prev is not None:
            flow = cv2.calcOpticalFlowFarneback(prev, small, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            fx, fy = flow[..., 0], flow[..., 1]
            feats["dx"].append(float(np.median(fx)))
            feats["dy"].append(float(np.median(fy)))
            feats["div"].append(float(np.mean(fx * rx + fy * ry)))
        else:
            feats["dx"].append(0.0); feats["dy"].append(0.0); feats["div"].append(0.0)
        prev = small
        g = gray.astype(np.float32)
        feats["luma"].append(float(g.mean()))
        feats["contrast"].append(float(g.std()))
        feats["center_ratio"].append(float((g[center].mean() + 1) / (g[~center].mean() + 1)))
        b, _, r = [bgr[..., i].astype(np.float32).mean() for i in range(3)]
        feats["warmth"].append(float((r + 1) / (b + 1)))
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        feats["sat"].append(float(hsv[..., 1].mean()))
        feats["clip_hi"].append(float((gray >= 250).mean()))
        feats["clip_lo"].append(float((gray <= 5).mean()))
    proc.wait()
    return {k: np.array(v, np.float32) for k, v in feats.items()}


def classify_motion(dx, dy, div):
    """单位：分析分辨率(160 宽)下 像素/帧（10fps）。"""
    if len(dx) < 3:
        return "固定", {}
    mdx, mdy, mdiv = float(np.mean(dx)), float(np.mean(dy)), float(np.mean(div))
    speed = float(np.hypot(mdx, mdy))
    jitter = float(np.mean(np.hypot(np.diff(dx), np.diff(dy))))
    stats = {"pan_px": round(mdx, 3), "tilt_px": round(mdy, 3), "zoom": round(mdiv, 3),
             "jitter": round(jitter, 3)}
    if jitter > 1.2 and jitter > 1.5 * speed:
        return "手持晃动", stats
    if abs(mdiv) > 0.25 and abs(mdiv) > 0.5 * speed:
        return ("推近" if mdiv > 0 else "拉远"), stats
    if speed < 0.15:
        return "固定", stats
    if abs(mdx) >= abs(mdy):
        return "横移", stats
    return "纵移/俯仰", stats


def per_shot(shots, F):
    n = len(F["luma"])
    for s in shots:
        a = int(s["start"] * AFPS) + 1
        b = max(a + 1, int(s["end"] * AFPS) - 1)
        sl = slice(min(a, n - 1), min(b, n))
        if sl.stop - sl.start < 1:
            sl = slice(max(0, min(a, n - 1)), min(a + 1, n))
        motion, mstats = classify_motion(F["dx"][sl], F["dy"][sl], F["div"][sl])
        s["motion"] = motion
        s["motion_stats"] = mstats
        s["light"] = {
            "luma": round(float(F["luma"][sl].mean()), 1),
            "contrast": round(float(F["contrast"][sl].mean()), 1),
            "center_vs_edge": round(float(F["center_ratio"][sl].mean()), 2),
            "warmth_rb": round(float(F["warmth"][sl].mean()), 2),
            "saturation": round(float(F["sat"][sl].mean()), 1),
            "clipped_hi": round(float(F["clip_hi"][sl].mean()), 3),
            "crushed_lo": round(float(F["clip_lo"][sl].mean()), 3),
        }


# ---------------------------------------------------------------- 关键帧联系表
def keyframes_and_sheets(path, shots, run_dir):
    kdir = os.path.join(run_dir, "keyframes")
    sdir = os.path.join(run_dir, "sheets")
    os.makedirs(kdir, exist_ok=True)
    os.makedirs(sdir, exist_ok=True)
    for s in shots:
        t = s["start"] + s["len"] / 2
        out = os.path.join(kdir, f"{s['idx']:04d}.jpg")
        if not os.path.exists(out):
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", path,
                 "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", out], check=False)
        s["keyframe"] = os.path.relpath(out, run_dir)

    per = SHEET_COLS * SHEET_ROWS
    for p in range(0, len(shots), per):
        page = shots[p:p + per]
        rows = (len(page) + SHEET_COLS - 1) // SHEET_COLS
        canvas = np.full((rows * (TILE_H + 4), SHEET_COLS * (TILE_W + 4), 3), 20, np.uint8)
        for j, s in enumerate(page):
            img = cv2.imread(os.path.join(run_dir, s["keyframe"]))
            if img is None:
                continue
            img = cv2.resize(img, (TILE_W, TILE_H))
            label = f"#{s['idx']} {fmt_t(s['start'])} {s['len']:.1f}s"
            cv2.rectangle(img, (0, 0), (len(label) * 11 + 10, 26), (0, 0, 0), -1)
            cv2.putText(img, label, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (255, 255, 255), 1, cv2.LINE_AA)
            r, c = divmod(j, SHEET_COLS)
            y, x = r * (TILE_H + 4), c * (TILE_W + 4)
            canvas[y:y + TILE_H, x:x + TILE_W] = img
        cv2.imwrite(os.path.join(sdir, f"sheet_{p // per + 1:02d}.jpg"), canvas,
                    [cv2.IMWRITE_JPEG_QUALITY, 82])


def fmt_t(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


# ---------------------------------------------------------------- ④ 声音
def audio_analysis(path, run_dir, use_asr):
    wav = os.path.join(run_dir, "audio.wav")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-vn", "-ac", "1",
                        "-ar", "22050", wav], capture_output=True)
    if r.returncode != 0 or not os.path.exists(wav):
        return {"has_audio": False}
    import librosa
    y, sr = librosa.load(wav, sr=22050, mono=True)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=False)
    rms = librosa.feature.rms(y=y)[0]
    out = {"has_audio": True,
           "tempo_bpm": round(float(np.atleast_1d(tempo)[0]), 1),
           "beats": [round(float(t), 3) for t in librosa.frames_to_time(beats, sr=sr)],
           "onsets": [round(float(t), 3) for t in onsets],
           "loudness_db_mean": round(float(20 * np.log10(rms.mean() + 1e-9)), 1)}
    if use_asr:
        out.update(transcribe(wav))
    return out


def transcribe(wav):
    words, segments = [], []
    try:
        import mlx_whisper   # Apple Silicon 首选
        res = mlx_whisper.transcribe(wav, word_timestamps=True,
                                     path_or_hf_repo="mlx-community/whisper-small-mlx")
        engine = "mlx-whisper"
        segs = res.get("segments", [])
    except ImportError:
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel("small", compute_type="int8")
            it, _ = model.transcribe(wav, word_timestamps=True)
            segs = [{"start": s.start, "end": s.end, "text": s.text,
                     "words": [{"start": w.start, "end": w.end, "word": w.word}
                               for w in (s.words or [])]} for s in it]
            engine = "faster-whisper"
        except ImportError:
            log("⚠️  没装 whisper（pip3 install mlx-whisper），跳过语音转录")
            return {"asr": None}
    for s in segs:
        segments.append({"start": round(s["start"], 2), "end": round(s["end"], 2),
                         "text": s["text"].strip()})
        for w in s.get("words", []) or []:
            words.append({"start": round(w["start"], 2), "end": round(w["end"], 2),
                          "w": w["word"].strip()})
    sentence_ends = [w["end"] for w in words if re.search(r"[.!?。！？]$", w["w"])]
    if not sentence_ends:
        sentence_ends = [s["end"] for s in segments]
    pauses = [{"start": round(a["end"], 2), "end": round(b["start"], 2),
               "len": round(b["start"] - a["end"], 2)}
              for a, b in zip(words, words[1:]) if b["start"] - a["end"] >= 0.35]
    speech_time = sum(w["end"] - w["start"] for w in words)
    return {"asr": engine, "segments": segments, "words": words,
            "sentence_ends": sentence_ends, "pauses": pauses,
            "words_per_min": round(len(words) / (speech_time / 60), 1) if speech_time else None}


# ---------------------------------------------------------------- ⑥ 切点对齐
def near(t, arr, before, after):
    arr = np.asarray(arr)
    return bool(len(arr)) and bool(np.any((arr >= t - before) & (arr <= t + after)))


def cut_alignment(shots, audio):
    cuts = [s["start"] for s in shots[1:]]
    tags = []
    for c in cuts:
        t = {"t": c}
        if audio.get("sentence_ends"):
            t["sentence_end"] = near(c, audio["sentence_ends"], 0.4, 0.15)
            t["in_pause"] = any(p["start"] - 0.1 <= c <= p["end"] + 0.1
                                for p in audio.get("pauses", []))
            t["mid_word"] = any(w["start"] + 0.05 < c < w["end"] - 0.05
                                for w in audio.get("words", []))
        if audio.get("beats"):
            t["on_beat"] = near(c, audio["beats"], 0.08, 0.08)
        if audio.get("onsets"):
            t["on_onset"] = near(c, audio["onsets"], 0.06, 0.06)
        tags.append(t)
    keys = ["sentence_end", "in_pause", "mid_word", "on_beat", "on_onset"]
    summary = {k: round(float(np.mean([x[k] for x in tags if k in x])), 2)
               for k in keys if any(k in x for x in tags)}
    return tags, summary


# ---------------------------------------------------------------- ⑦ 汇总
def summarize(shots, meta, audio, align_summary):
    lens = np.array([s["len"] for s in shots])
    dur = meta["duration"]

    def section(a, b):
        sel = [s["len"] for s in shots if a <= s["start"] < b]
        return round(float(np.mean(sel)), 2) if sel else None

    motions = {}
    for s in shots:
        motions[s["motion"]] = motions.get(s["motion"], 0) + s["len"]
    motions = {k: round(v / dur, 2) for k, v in sorted(motions.items(), key=lambda x: -x[1])}

    window = 10
    curve = [{"t": t, "cuts": sum(1 for s in shots[1:] if t <= s["start"] < t + window)}
             for t in range(0, int(dur), window)]
    L = lambda k: float(np.average([s["light"][k] for s in shots], weights=lens))
    return {
        "shots": len(shots),
        "cuts_per_min": round((len(shots) - 1) / (dur / 60), 1),
        "shot_len": {"mean": round(float(lens.mean()), 2),
                     "median": round(float(np.median(lens)), 2),
                     "p10": round(float(np.percentile(lens, 10)), 2),
                     "p90": round(float(np.percentile(lens, 90)), 2)},
        "shot_len_by_section": {"first_30s": section(0, 30),
                                "middle": section(30, max(30, dur - 30)),
                                "last_30s": section(max(30, dur - 30), dur + 1)},
        "motion_share_by_time": motions,
        "cut_alignment": align_summary,
        "speech": {"words_per_min": audio.get("words_per_min"),
                   "pauses_over_0_35s": len(audio.get("pauses", []) or [])},
        "music_tempo_bpm": audio.get("tempo_bpm"),
        "look_weighted": {k: round(L(k), 2) for k in
                          ("luma", "contrast", "center_vs_edge", "warmth_rb", "saturation")},
        "rhythm_curve_10s": curve,
    }


def plot_rhythm(shots, summary, run_dir):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 5), sharex=True)
    c = summary["rhythm_curve_10s"]
    a1.bar([x["t"] for x in c], [x["cuts"] for x in c], width=9, color="#4a7bd0")
    a1.set_ylabel("cuts / 10s")
    a2.scatter([s["start"] for s in shots], [s["len"] for s in shots], s=8, color="#d0714a")
    a2.set_ylabel("shot length (s)")
    a2.set_xlabel("time (s)")
    for a in (a1, a2):
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(run_dir, "rhythm.png"), dpi=110)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="video-lab：视频测量层")
    ap.add_argument("src", help="YouTube 链接或本地视频路径")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--no-asr", action="store_true", help="跳过语音转录（纯音乐视频）")
    args = ap.parse_args()
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit("❌ 需要 ffmpeg：brew install ffmpeg")

    path, run_dir, info = fetch(args.src, args.out)
    os.makedirs(run_dir, exist_ok=True)
    meta = probe(path)
    log(f"🎬 {info.get('title') or os.path.basename(path)}  "
        f"{meta['width']}x{meta['height']} {meta['fps']}fps {meta['duration'] / 60:.1f}min")

    log("✂️  切镜头 ...")
    shots = detect_shots(path, meta["duration"])
    log(f"   {len(shots)} 个镜头")
    log("👁️  运镜 + 光线 ...")
    per_shot(shots, frame_features(path))
    log("🖼️  关键帧联系表 ...")
    keyframes_and_sheets(path, shots, run_dir)
    log("🔊 声音 ..." + ("（含转录，第一次会下载模型）" if not args.no_asr else ""))
    audio = audio_analysis(path, run_dir, not args.no_asr)
    tags, align = cut_alignment(shots, audio)
    for s, t in zip(shots[1:], tags):
        s["cut_in"] = {k: v for k, v in t.items() if k != "t"}

    summary = summarize(shots, meta, audio, align)
    evidence = {"video": {**info, **meta}, "summary": summary, "shots": shots,
                "audio": {k: v for k, v in audio.items() if k not in ("words",)},
                "transcript_words": audio.get("words")}
    with open(os.path.join(run_dir, "evidence.json"), "w") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=1)
    plot_rhythm(shots, summary, run_dir)

    s = summary
    log(f"\n✅ 完成 → {run_dir}")
    log(f"   平均镜头 {s['shot_len']['mean']}s（中位 {s['shot_len']['median']}s），"
        f"每分钟 {s['cuts_per_min']} 刀")
    sec = {k: ("-" if v is None else f"{v}s") for k, v in s["shot_len_by_section"].items()}
    log(f"   分段：开头 {sec['first_30s']} / 中段 {sec['middle']} / 结尾 {sec['last_30s']}")
    log(f"   运镜占比：{s['motion_share_by_time']}")
    log(f"   切点对齐：{s['cut_alignment']}")
    log("👉 把这个文件夹交给 Claude，按 docs/CONCLUSIONS.md 出反向结论。")


if __name__ == "__main__":
    main()
