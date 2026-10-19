"""融合层：在每个切点处查时间轴，判断切点和声音 / 动作的关系；再把镜头表 + 时间轴汇总成指标。"""
import numpy as np

from .config import ACTION_RATIO, AFPS, WIN_BEAT, WIN_SENTENCE, WIN_SFX
from .util import share


def tag_cut(ctx, s, prev):
    tl, c = ctx.timeline, s["start"]
    t = s.setdefault("cut_in", {})
    if tl.of("word"):
        t["sentence_end"] = tl.near("sentence_end", c, *WIN_SENTENCE)
        t["mid_word"] = bool(tl.covering("word", c, margin=0.05))
        t["in_pause"] = bool(tl.covering("pause", c, margin=-0.1))
        # 声音跨过切点（J/L-cut 候选）：有词跨切点，或前后 0.15s 内都有人声
        words = tl.of("word")
        before = any(w["end"] > c - 0.15 and w["t"] < c for w in words)
        after = any(w["t"] < c + 0.15 and w["end"] > c for w in words)
        t["speech_bridges_cut"] = bool(t["mid_word"] or (before and after))
    if tl.of("beat"):
        t["on_beat"] = tl.near("beat", c, WIN_BEAT, WIN_BEAT)
    if tl.of("onset"):
        t["on_onset"] = tl.near("onset", c, WIN_SFX, WIN_SFX)
    if tl.of("sfx"):
        t["on_sfx"] = tl.near("sfx", c, WIN_SFX, WIN_SFX)
    mag = ctx.frames.get("mag")
    if mag is not None and len(mag):
        k = int(round(c * AFPS))
        before = mag[max(0, k - 3):k]
        sl = ctx.shot_slice(prev)
        base = float(np.median(mag[sl])) if sl.stop > sl.start else 0.0
        t["on_action"] = bool(len(before) and before.mean() > ACTION_RATIO * (base + 0.05)
                              and before.mean() > 0.3)


def frac(shots, key):
    vals = [s["cut_in"][key] for s in shots if key in s.get("cut_in", {})]
    return round(float(np.mean(vals)), 2) if vals else None


def summarize(ctx):
    shots, dur, tl = ctx.shots, ctx.meta["duration"], ctx.timeline
    lens = np.array([s["len"] for s in shots])
    cut_shots = shots[1:]

    def section(a, b):
        sel = [s["len"] for s in shots if a <= s["start"] < b]
        return round(float(np.mean(sel)), 2) if sel else None

    def get(s, *path):
        for p in path:
            s = (s or {}).get(p)
        return s

    scales = [get(s, "composition", "shot_scale") or "未知" for s in shots]
    len_by_scale = {}
    for sc, s in zip(scales, shots):
        len_by_scale.setdefault(sc, []).append(s["len"])
    moving = [s for s in shots if get(s, "motion", "ease_in") is not None]
    lateral = [s for s in shots if get(s, "motion", "parallax")]

    # 说话时画面不是“说话人”（无人脸或全景）的比例 —— B-roll 覆盖率近似
    words = tl.of("word")
    broll = None
    if words:
        speech = talk = 0.0
        for w in words:
            d = w["end"] - w["t"]
            sh = next((s for s in shots if s["start"] <= w["t"] < s["end"]), None)
            speech += d
            if sh and get(sh, "composition", "shot_scale") in ("无人脸", "全景"):
                talk += d
        broll = round(talk / speech, 2) if speech else None

    labs = np.array([s["lab_mean"] for s in shots if s.get("lab_mean")])
    first15 = [s for s in shots if s["start"] < 15]

    ctx.summary = {
        "shots": len(shots),
        "cuts_per_min": round((len(shots) - 1) / (dur / 60), 1) if dur else None,
        "shot_len": {"mean": round(float(lens.mean()), 2),
                     "median": round(float(np.median(lens)), 2),
                     "p10": round(float(np.percentile(lens, 10)), 2),
                     "p90": round(float(np.percentile(lens, 90)), 2)},
        "shot_len_by_section": {"first_30s": section(0, 30),
                                "middle": section(30, max(30, dur - 30)),
                                "last_30s": section(max(30, dur - 30), dur + 1)},
        "hook_first_15s": {"cuts": max(0, len(first15) - 1),
                           "words": sum(1 for w in words if w["t"] < 15)},
        "transitions": share([s["cut_in"].get("transition", "?") for s in cut_shots]),
        "cut_kinds": share([s["cut_in"].get("kind", "?") for s in cut_shots]),
        "cut_alignment": {k: frac(cut_shots, k) for k in
                          ("sentence_end", "mid_word", "in_pause", "speech_bridges_cut",
                           "on_beat", "on_onset", "on_sfx", "on_action")},
        "shot_scale_share_by_time": share(scales, list(lens)),
        "shot_len_by_scale": {k: round(float(np.mean(v)), 2) for k, v in len_by_scale.items()},
        "position_share": share([get(s, "composition", "position") or "?" for s in shots]),
        "dof_share": share([get(s, "composition", "dof") or "?" for s in shots], list(lens)),
        "symmetry_mean": round(float(np.mean([get(s, "composition", "symmetry") or 0
                                              for s in shots])), 2),
        "motion_share_by_time": share([get(s, "motion", "type") or "?" for s in shots],
                                      list(lens)),
        "ease_in_out_share": {
            "ease_in": round(float(np.mean([get(s, "motion", "ease_in") for s in moving])), 2)
            if moving else None,
            "ease_out": round(float(np.mean([get(s, "motion", "ease_out") for s in moving])), 2)
            if moving else None},
        "parallax_share": share([get(s, "motion", "parallax") for s in lateral]),
        "look_weighted": {k: round(float(np.average([s["light"][k] for s in shots],
                                                    weights=lens)), 2)
                          for k in ("luma", "contrast", "p5", "p95", "warmth", "sat",
                                    "center_ratio")} if all("light" in s for s in shots) else {},
        "grade_consistency": {"lab_std_L": round(float(labs[:, 0].std()), 1),
                              "lab_std_a": round(float(labs[:, 1].std()), 1),
                              "lab_std_b": round(float(labs[:, 2].std()), 1)}
        if len(labs) > 1 else None,
        "key_light_share": share([get(s, "light", "key_side") for s in shots
                                  if get(s, "light", "key_side")]),
        "broll_coverage_during_speech": broll,
        "shots_per_sentence": round((len(shots) - 1) / ctx.audio["sentences"], 2)
        if ctx.audio.get("sentences") else None,
        "audio": {k: ctx.audio.get(k) for k in ("tempo_bpm", "lufs", "rms_db", "ducking_db",
                                                 "sfx_per_min", "words_per_min")},
        "text_on_screen_shots": sum(1 for s in shots if s.get("text")),
        "rhythm_curve_10s": [{"t": t, "cuts": sum(1 for s in cut_shots
                                                  if t <= s["start"] < t + 10)}
                             for t in range(0, int(dur), 10)],
    }


def run(ctx):
    for prev, s in zip(ctx.shots, ctx.shots[1:]):
        tag_cut(ctx, s, prev)
    summarize(ctx)
    return "完成"
