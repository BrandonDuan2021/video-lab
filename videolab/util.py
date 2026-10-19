import importlib
import importlib.util
import json
import platform
import re
import subprocess
import sys

import cv2
import numpy as np

IS_MAC = platform.system() == "Darwin"


def log(msg):
    print(msg, flush=True)


def run(cmd, check=True):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and r.returncode != 0:
        print(r.stderr[-1500:])
        sys.exit(f"❌ 命令失败: {' '.join(map(str, cmd[:6]))} ...")
    return r.stdout


def has_module(name):
    return importlib.util.find_spec(name) is not None


def optional(name):
    """可选依赖：装了就返回模块，没装返回 None。"""
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def hwaccel():
    return ["-hwaccel", "videotoolbox"] if IS_MAC else []


def probe(path):
    info = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                           "-of", "json", path]))
    s = info["streams"][0]
    n, d = s["r_frame_rate"].split("/")
    return {"width": s["width"], "height": s["height"],
            "fps": round(float(n) / float(d), 3),
            "duration": round(float(info["format"]["duration"]), 3)}


def grab_frame(path, t, width):
    """取单帧（BGR）。"""
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", path,
                        "-frames:v", "1", "-vf", f"scale={width}:-2",
                        "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    return cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)


def fmt_t(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def slugify(s):
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE).strip("_")
    return s[:60] or "video"


def share(items, weights=None):
    """计数 / 加权占比，按大小排序。"""
    tot, acc = 0.0, {}
    for i, k in enumerate(items):
        w = 1.0 if weights is None else float(weights[i])
        acc[k] = acc.get(k, 0.0) + w
        tot += w
    return {k: round(v / tot, 2) for k, v in sorted(acc.items(), key=lambda x: -x[1])} if tot else {}
