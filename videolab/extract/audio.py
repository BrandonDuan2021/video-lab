"""声音。全部依赖都是可选的，缺哪个跳哪个：
  demucs   分轨：人声 / 鼓 / 贝斯 / 其他 → 音乐 = 后三轨相加
  whisperx > mlx-whisper > faster-whisper   逐字时间戳（优先用分出来的人声轨，更干净）
  librosa  节拍（音乐轨）、起音点、音效候选
  pyloudnorm 响度 LUFS
输出：ctx.audio 汇总 + 时间轴事件 word / sentence_end / pause / beat / onset / sfx
"""
import json
import os
import subprocess
import sys

import numpy as np

from ..config import WIN_SFX
from ..decode import extract_audio
from ..util import has_module, log, optional

SR = 22050


# ------------------------------------------------------------------ 分轨
def separate(wav, run_dir):
    out = os.path.join(run_dir, "stems")
    name = os.path.splitext(os.path.basename(wav))[0]
    stem_dir = os.path.join(out, "htdemucs", name)
    paths = {k: os.path.join(stem_dir, f"{k}.wav") for k in ("vocals", "drums", "bass", "other")}
    if not all(os.path.exists(p) for p in paths.values()):
        log("   🎚️  demucs 分轨（第一次会下载模型，10 分钟音频大约几分钟）...")
        r = subprocess.run([sys.executable, "-m", "demucs", "-n", "htdemucs", "-o", out, wav],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr[-800:])
            return None
    return paths


# ------------------------------------------------------------------ 转录
def transcribe(path, cache):
    if os.path.exists(cache):
        return json.load(open(cache))
    words, segs, engine = [], [], None
    if has_module("whisperx"):
        import whisperx
        audio = whisperx.load_audio(path)
        model = whisperx.load_model("small", "cpu", compute_type="int8")
        res = model.transcribe(audio, batch_size=8)
        am, md = whisperx.load_align_model(language_code=res["language"], device="cpu")
        res = whisperx.align(res["segments"], am, md, audio, "cpu",
                             return_char_alignments=False)
        segs, engine = res["segments"], "whisperx"
    elif has_module("mlx_whisper"):
        import mlx_whisper
        res = mlx_whisper.transcribe(path, word_timestamps=True,
                                     path_or_hf_repo="mlx-community/whisper-small-mlx")
        segs, engine = res.get("segments", []), "mlx-whisper"
    elif has_module("faster_whisper"):
        from faster_whisper import WhisperModel
        it, _ = WhisperModel("small", compute_type="int8").transcribe(path, word_timestamps=True)
        segs = [{"start": s.start, "end": s.end, "text": s.text,
                 "words": [{"start": w.start, "end": w.end, "word": w.word}
                           for w in (s.words or [])]} for s in it]
        engine = "faster-whisper"
    else:
        return None
    for s in segs:
        for w in s.get("words", []) or []:
            if w.get("start") is None or w.get("end") is None:
                continue
            words.append({"t": round(float(w["start"]), 3), "end": round(float(w["end"]), 3),
                          "w": str(w["word"]).strip()})
    out = {"engine": engine, "words": words,
           "segments": [{"t": round(float(s["start"]), 2), "end": round(float(s["end"]), 2),
                         "text": s.get("text", "").strip()} for s in segs]}
    json.dump(out, open(cache, "w"), ensure_ascii=False)
    return out


# ------------------------------------------------------------------ 主流程
def run(ctx):
    wav = extract_audio(ctx.path, ctx.run_dir, SR)
    if wav is None:
        ctx.skip("声音", "视频没有音轨")
        return "跳过"
    a = {"has_audio": True}

    stems = None
    if ctx.opts.get("no_stems"):
        ctx.skip("分轨", "--no-stems")
    elif not has_module("demucs"):
        ctx.skip("分轨", "没装 demucs（pip3 install demucs）；闪避 / 音效检测会不可用")
    else:
        stems = separate(wav, ctx.run_dir)
        if stems is None:
            ctx.skip("分轨", "demucs 运行失败")
    a["stems"] = bool(stems)

    # 转录
    if ctx.opts.get("no_asr"):
        ctx.skip("转录", "--no-asr")
        tr = None
    else:
        src = stems["vocals"] if stems else wav
        tr = transcribe(src, os.path.join(ctx.run_dir, "transcript.json"))
        if tr is None:
            ctx.skip("转录", "没装 whisper（pip3 install whisperx 或 mlx-whisper）")
    if tr:
        a["asr"] = tr["engine"]
        words = tr["words"]
        for w in words:
            ctx.timeline.add("word", w["t"], w["end"], w=w["w"])
        ends = [w["end"] for w in words if w["w"][-1:] in ".!?。！？"] or \
               [s["end"] for s in tr["segments"]]
        for t in ends:
            ctx.timeline.add("sentence_end", t)
        for p, q in zip(words, words[1:]):
            if q["t"] - p["end"] >= 0.35:
                ctx.timeline.add("pause", p["end"], q["t"], len=round(q["t"] - p["end"], 2))
        speech = sum(w["end"] - w["t"] for w in words)
        a["words"] = len(words)
        a["sentences"] = len(ends)
        a["speech_s"] = round(speech, 1)
        a["words_per_min"] = round(len(words) / (speech / 60), 1) if speech else None

    # 节拍 / 起音 / 音效 / 闪避 / 响度
    librosa = optional("librosa")
    if librosa is None:
        ctx.skip("节拍 / 音效", "没装 librosa（pip3 install librosa）")
    else:
        y_mix, _ = librosa.load(wav, sr=SR, mono=True)
        if stems:
            parts = [librosa.load(stems[k], sr=SR, mono=True)[0] for k in ("drums", "bass", "other")]
            n = min(len(p) for p in parts)
            y_music = sum(p[:n] for p in parts)
        else:
            y_music = y_mix
        tempo, bf = librosa.beat.beat_track(y=y_music, sr=SR)
        beats = librosa.frames_to_time(bf, sr=SR)
        a["tempo_bpm"] = round(float(np.atleast_1d(tempo)[0]), 1)
        for t in beats:
            ctx.timeline.add("beat", t)
        env = librosa.onset.onset_strength(y=y_music, sr=SR)
        on_f = librosa.onset.onset_detect(onset_envelope=env, sr=SR)
        on_t = librosa.frames_to_time(on_f, sr=SR)
        for t in on_t:
            ctx.timeline.add("onset", t)
        if stems:
            # 音效候选：很强、又不在节拍上的起音点（近似，结论层要看图 / 听确认）
            strong = env[on_f] >= np.percentile(env[on_f], 85) if len(on_f) else []
            sfx = [float(t) for t, st in zip(on_t, strong)
                   if st and not np.any(np.abs(beats - t) <= WIN_SFX)]
            for t in sfx:
                ctx.timeline.add("sfx", t)
            dur = len(y_mix) / SR
            a["sfx_per_min"] = round(len(sfx) / (dur / 60), 1)
            # 闪避：说话时音乐比不说话时低多少 dB
            if tr and tr["words"]:
                hop = 512
                rms = librosa.feature.rms(y=y_music, hop_length=hop)[0]
                db = 20 * np.log10(rms + 1e-6)
                tt = librosa.frames_to_time(np.arange(len(db)), sr=SR, hop_length=hop)
                mask = np.zeros(len(db), bool)
                for w in tr["words"]:
                    mask |= (tt >= w["t"]) & (tt <= w["end"])
                if mask.any() and (~mask).sum() > 20:
                    a["ducking_db"] = round(float(db[~mask].mean() - db[mask].mean()), 1)
        pyln = optional("pyloudnorm")
        if pyln is not None:
            a["lufs"] = round(float(pyln.Meter(SR).integrated_loudness(y_mix)), 1)
        else:
            a["rms_db"] = round(float(20 * np.log10(np.sqrt(np.mean(y_mix ** 2)) + 1e-9)), 1)
    ctx.audio = a
    return ", ".join(f"{k}={v}" for k, v in a.items() if k in ("asr", "tempo_bpm", "lufs"))
