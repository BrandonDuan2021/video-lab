#!/usr/bin/env python3
"""
对比模式：参考视频 vs 你的视频，按差距大小列出来
  python3 compare.py runs/<参考>/evidence.json runs/<你的>/evidence.json
输出 gap.json（放在你的视频那个文件夹）+ 终端表格。
把 gap.json 一起交给 Claude，结论层会写成“改进清单”。
"""
import json
import os
import sys


def get(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


METRICS = [
    ("summary.shot_len.mean", "平均镜头时长 s"),
    ("summary.shot_len.median", "中位镜头时长 s"),
    ("summary.cuts_per_min", "每分钟切几刀"),
    ("summary.shot_len_by_section.first_30s", "开头 30s 平均镜头 s"),
    ("summary.shot_len_by_section.middle", "中段平均镜头 s"),
    ("summary.cut_alignment.sentence_end", "切在句末的比例"),
    ("summary.cut_alignment.mid_word", "切在词中间的比例（越低越好）"),
    ("summary.cut_alignment.on_beat", "切在节拍上的比例"),
    ("summary.speech.words_per_min", "语速 词/分"),
    ("summary.look_weighted.contrast", "对比度"),
    ("summary.look_weighted.center_vs_edge", "主体/背景亮度比"),
    ("summary.look_weighted.warmth_rb", "色温（R/B，>1 偏暖）"),
    ("summary.look_weighted.saturation", "饱和度"),
]


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    ref, mine = (json.load(open(p)) for p in sys.argv[1:3])
    rows = []
    for key, label in METRICS:
        a, b = get(ref, key), get(mine, key)
        if a is None or b is None:
            continue
        rel = abs(b - a) / (abs(a) + 1e-6)
        rows.append({"metric": label, "key": key, "reference": a, "mine": b,
                     "gap_pct": round(rel * 100)})
    ma, mb = ref["summary"]["motion_share_by_time"], mine["summary"]["motion_share_by_time"]
    for k in sorted(set(ma) | set(mb)):
        a, b = ma.get(k, 0), mb.get(k, 0)
        rows.append({"metric": f"运镜占比：{k}", "key": f"motion.{k}", "reference": a,
                     "mine": b, "gap_pct": round(abs(b - a) * 100)})
    rows.sort(key=lambda r: -r["gap_pct"])

    w = max(len(r["metric"]) for r in rows) + 2
    print(f"{'指标'.ljust(w)}{'参考':>10}{'你的':>10}{'差距':>8}")
    for r in rows:
        print(f"{r['metric'].ljust(w)}{r['reference']:>10}{r['mine']:>10}{r['gap_pct']:>7}%")

    out = os.path.join(os.path.dirname(os.path.abspath(sys.argv[2])), "gap.json")
    with open(out, "w") as f:
        json.dump({"reference": ref["video"].get("title") or ref["video"].get("source"),
                   "mine": mine["video"].get("title") or mine["video"].get("source"),
                   "gaps": rows}, f, ensure_ascii=False, indent=1)
    print(f"\n✅ {out}")


if __name__ == "__main__":
    main()
