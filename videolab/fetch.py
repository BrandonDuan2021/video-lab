import json
import os
import shutil
import sys

from .util import log, run, slugify


def fetch(src, out_root):
    """本地文件直接用；链接用 yt-dlp 下 720p。返回 (视频路径, 结果目录, 来源信息)。"""
    local = os.path.expanduser(src)
    if os.path.exists(local):
        path = os.path.abspath(local)
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
    return path, run_dir, {"source": src, "title": meta.get("title"),
                           "uploader": meta.get("uploader"),
                           "upload_date": meta.get("upload_date")}
