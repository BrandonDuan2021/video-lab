"""输出：evidence.json（给结论层）、sheets/（关键帧联系表）、rhythm.png、report.md（人看的速览）。"""
import json
import os

import cv2
import numpy as np

from .config import SHEET_COLS, SHEET_ROWS, TILE_H, TILE_W
from .util import fmt_t


def _label(img, lines):
    for j, text in enumerate(lines):
        y = 4 + j * 24
        cv2.rectangle(img, (0, y), (len(text) * 10 + 12, y + 22), (0, 0, 0), -1)
        cv2.putText(img, text, (6, y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 1, cv2.LINE_AA)


def sheets(ctx):
    """标签只用 ASCII（OpenCV 画不了中文）：编号 时间 时长 / 景别 运镜 切法 的缩写。"""
    abbr = {"大特写": "ECU", "特写": "CU", "近景": "MCU", "中景": "MS", "全景": "WS",
            "无人脸": "-", "固定": "static", "横移": "pan", "纵移/俯仰": "tilt",
            "推近": "push", "拉远": "pull", "手持晃动": "handheld",
            "跳切(同机位)": "jump", "推镜(punch-in)": "punch-in",
            "拉镜(punch-out)": "punch-out", "换镜头": "cut"}
    sdir = os.path.join(ctx.run_dir, "sheets")
    os.makedirs(sdir, exist_ok=True)
    per = SHEET_COLS * SHEET_ROWS
    for p in range(0, len(ctx.shots), per):
        page = ctx.shots[p:p + per]
        rows = (len(page) + SHEET_COLS - 1) // SHEET_COLS
        canvas = np.full((rows * (TILE_H + 4), SHEET_COLS * (TILE_W + 4), 3), 20, np.uint8)
        for j, s in enumerate(page):
            img = cv2.imread(os.path.join(ctx.run_dir, s.get("keyframe", ""))) \
                if s.get("keyframe") else None
            if img is None:
                continue
            img = cv2.resize(img, (TILE_W, TILE_H))
            sc = abbr.get((s.get("composition") or {}).get("shot_scale"), "?")
            mo = abbr.get((s.get("motion") or {}).get("type"), "?")
            ck = abbr.get((s.get("cut_in") or {}).get("kind"), "")
            _label(img, [f"#{s['idx']} {fmt_t(s['start'])} {s['len']:.1f}s",
                         f"{sc} {mo} {ck}".strip()])
            r, c = divmod(j, SHEET_COLS)
            canvas[r * (TILE_H + 4): r * (TILE_H + 4) + TILE_H,
                   c * (TILE_W + 4): c * (TILE_W + 4) + TILE_W] = img
        cv2.imwrite(os.path.join(sdir, f"sheet_{p // per + 1:02d}.jpg"), canvas,
                    [cv2.IMWRITE_JPEG_QUALITY, 82])


def rhythm_plot(ctx):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    c = ctx.summary["rhythm_curve_10s"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 5), sharex=True)
    a1.bar([x["t"] for x in c], [x["cuts"] for x in c], width=9, color="#4a7bd0")
    a1.set_ylabel("cuts / 10s")
    a2.scatter([s["start"] for s in ctx.shots], [s["len"] for s in ctx.shots], s=8,
               color="#d0714a")
    a2.set_ylabel("shot length (s)")
    a2.set_xlabel("time (s)")
    for a in (a1, a2):
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(ctx.run_dir, "rhythm.png"), dpi=110)
    plt.close(fig)


def _np_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def write(ctx):
    ev = {"version": 2, "video": {**ctx.info, **ctx.meta}, "skipped": ctx.skipped,
          "summary": ctx.summary, "audio": ctx.audio, "shots": ctx.shots,
          "timeline": ctx.timeline.events}
    with open(os.path.join(ctx.run_dir, "evidence.json"), "w") as f:
        json.dump(ev, f, ensure_ascii=False, indent=1, default=_np_default)
    sheets(ctx)
    rhythm_plot(ctx)
    s = ctx.summary
    md = [f"# {ctx.info.get('title') or os.path.basename(ctx.path)}", "",
          f"- 时长 {ctx.meta['duration'] / 60:.1f} 分钟，{s['shots']} 个镜头，每分钟 {s['cuts_per_min']} 刀",
          f"- 镜头时长：平均 {s['shot_len']['mean']}s，中位 {s['shot_len']['median']}s",
          f"- 分段：{s['shot_len_by_section']}",
          f"- 开头 15 秒：{s['hook_first_15s']}",
          f"- 转场：{s['transitions']}",
          f"- 切法：{s['cut_kinds']}",
          f"- 切点对齐：{s['cut_alignment']}",
          f"- 景别（按时长）：{s['shot_scale_share_by_time']}",
          f"- 各景别平均时长：{s['shot_len_by_scale']}",
          f"- 运镜（按时长）：{s['motion_share_by_time']}",
          f"- 缓入缓出：{s['ease_in_out_share']}，视差：{s['parallax_share']}",
          f"- 景深：{s['dof_share']}，主体位置：{s['position_share']}",
          f"- 光线：{s['look_weighted']}，主光：{s['key_light_share']}",
          f"- 调色一致性（Lab 标准差，越小越统一）：{s['grade_consistency']}",
          f"- 说话时 B-roll 覆盖率：{s['broll_coverage_during_speech']}，每句话 {s['shots_per_sentence']} 个镜头",
          f"- 声音：{s['audio']}",
          "", "## 跳过的步骤", ""] + \
         ([f"- {x['step']}：{x['reason']}" for x in ctx.skipped] or ["- 无"])
    with open(os.path.join(ctx.run_dir, "report.md"), "w") as f:
        f.write("\n".join(md) + "\n")
