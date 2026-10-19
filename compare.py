#!/usr/bin/env python3
"""
对比模式：参考视频 vs 你的视频，按差距大小排序
  python3 compare.py runs/<参考>/evidence.json runs/<你的>/evidence.json
输出 gap.json（放在你的视频那个文件夹）+ 终端表格。把 gap.json 一起交给 Claude 出“改进清单”。
"""
import json
import os
import sys

NUM = [
    ("summary.shot_len.mean", "平均镜头时长 s"),
    ("summary.shot_len.median", "中位镜头时长 s"),
    ("summary.cuts_per_min", "每分钟切几刀"),
    ("summary.shot_len_by_section.first_30s", "开头 30s 平均镜头 s"),
    ("summary.shot_len_by_section.middle", "中段平均镜头 s"),
    ("summary.hook_first_15s.cuts", "开头 15s 切了几刀"),
    ("summary.cut_alignment.sentence_end", "切在句末的比例"),
    ("summary.cut_alignment.mid_word", "切在词中间的比例（越低越好）"),
    ("summary.cut_alignment.speech_bridges_cut", "声音跨切点比例（J/L-cut）"),
    ("summary.cut_alignment.on_beat", "切在节拍上的比例"),
    ("summary.cut_alignment.on_sfx", "切点配音效的比例"),
    ("summary.cut_alignment.on_action", "动作上切的比例"),
    ("summary.broll_coverage_during_speech", "说话时 B-roll 覆盖率"),
    ("summary.shots_per_sentence", "每句话几个镜头"),
    ("summary.symmetry_mean", "平均对称度"),
    ("summary.look_weighted.contrast", "对比度"),
    ("summary.look_weighted.center_ratio", "中心 / 边缘亮度比"),
    ("summary.look_weighted.warmth", "色温（R/B，>1 偏暖）"),
    ("summary.look_weighted.sat", "饱和度"),
    ("summary.grade_consistency.lab_std_b", "调色一致性：冷暖波动（越小越统一）"),
    ("summary.audio.words_per_min", "语速 词/分"),
    ("summary.audio.ducking_db", "音乐闪避 dB"),
    ("summary.audio.sfx_per_min", "每分钟音效数"),
    ("summary.audio.lufs", "响度 LUFS"),
]
SHARES = [
    ("summary.cut_kinds", "切法"),
    ("summary.transitions", "转场"),
    ("summary.shot_scale_share_by_time", "景别"),
    ("summary.motion_share_by_time", "运镜"),
    ("summary.dof_share", "景深"),
]


def get(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    ref, mine = (json.load(open(p)) for p in sys.argv[1:3])
    rows = []
    for key, label in NUM:
        a, b = get(ref, key), get(mine, key)
        if a is None or b is None:
            continue
        rows.append({"metric": label, "key": key, "reference": a, "mine": b,
                     "gap_pct": round(abs(b - a) / (abs(a) + 1e-6) * 100)})
    for key, label in SHARES:
        ma, mb = get(ref, key) or {}, get(mine, key) or {}
        for k in sorted(set(ma) | set(mb)):
            a, b = ma.get(k, 0), mb.get(k, 0)
            rows.append({"metric": f"{label}占比：{k}", "key": f"{key}.{k}", "reference": a,
                         "mine": b, "gap_pct": round(abs(b - a) * 100)})
    rows.sort(key=lambda r: -r["gap_pct"])

    w = max((len(r["metric"]) for r in rows), default=10) + 2
    print(f"{'指标'.ljust(w)}{'参考':>10}{'你的':>10}{'差距':>8}")
    for r in rows:
        print(f"{r['metric'].ljust(w)}{str(r['reference']):>10}{str(r['mine']):>10}"
              f"{r['gap_pct']:>7}%")

    out = os.path.join(os.path.dirname(os.path.abspath(sys.argv[2])), "gap.json")
    with open(out, "w") as f:
        json.dump({"reference": ref["video"].get("title") or ref["video"].get("source"),
                   "mine": mine["video"].get("title") or mine["video"].get("source"),
                   "skipped_reference": ref.get("skipped"), "skipped_mine": mine.get("skipped"),
                   "gaps": rows}, f, ensure_ascii=False, indent=1)
    print(f"\n✅ {out}")


if __name__ == "__main__":
    main()
