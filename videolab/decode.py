"""只解码一次：ffmpeg 输出 10fps 低清帧流，逐帧喂给所有“帧消费者”。
帧消费者（FrameConsumer）定义在各提取器里，每帧算几个数，最后交出逐帧数组。
这样不管加多少提取器，视频都只解码一遍，内存占用也是常数。
"""
import os
import subprocess

import cv2
import numpy as np

from .config import AFPS, AW, AH, FW, FH
from .util import hwaccel


class FrameConsumer:
    name = "base"

    def update(self, i, bgr, gray, small):
        raise NotImplementedError

    def result(self):
        """返回 {字段名: np.array}，长度 = 帧数。"""
        raise NotImplementedError


def frame_pass(path, consumers):
    proc = subprocess.Popen(["ffmpeg", "-v", "error"] + hwaccel() +
                            ["-i", path, "-vf", f"fps={AFPS},scale={AW}:{AH}",
                             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                            stdout=subprocess.PIPE)
    fsize = AW * AH * 3
    i = 0
    while True:
        buf = proc.stdout.read(fsize)
        if len(buf) < fsize:
            break
        bgr = np.frombuffer(buf, np.uint8).reshape(AH, AW, 3)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (FW, FH))
        for c in consumers:
            c.update(i, bgr, gray, small)
        i += 1
    proc.wait()
    frames = {}
    for c in consumers:
        frames.update(c.result())
    return frames


def extract_audio(path, run_dir, sr=22050):
    wav = os.path.join(run_dir, "audio.wav")
    if os.path.exists(wav):
        return wav
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-vn", "-ac", "1",
                        "-ar", str(sr), wav], capture_output=True)
    return wav if r.returncode == 0 and os.path.exists(wav) else None
