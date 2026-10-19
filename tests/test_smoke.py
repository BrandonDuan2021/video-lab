#!/usr/bin/env python3
"""冒烟测试：用 ffmpeg 生成一段合成视频（含硬切、推镜、黑场淡入），跑整条流水线。
只验证代码路径和几个能确定的判断，不代表真实视频上的准确度。
  python3 tests/test_smoke.py      （或 pytest tests/）
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def make_video(path):
    fc = ("[0:v]split=2[s1][s2];"
          "[s1]trim=0:3,setpts=PTS-STARTPTS[a];"
          "[s2]trim=3:6,setpts=PTS-STARTPTS,crop=iw/1.4:ih/1.4,scale=1280:720,setsar=1[b];"
          "[1:v]trim=0:3,setpts=PTS-STARTPTS,setsar=1[c];"
          "[2:v]trim=0:4,setpts=PTS-STARTPTS,fade=t=in:st=0:d=1,setsar=1[d];"
          "[a][b][c][d]concat=n=4:v=1[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=6",
                    "-f", "lavfi", "-i", "smptebars=s=1280x720:r=30:d=3",
                    "-f", "lavfi", "-i", "mandelbrot=s=1280x720:r=30",
                    "-f", "lavfi", "-i",
                    "aevalsrc='0.5*sin(2*PI*220*t)*exp(-10*mod(t\\,0.5))':s=44100:d=13",
                    "-filter_complex", fc, "-map", "[v]", "-map", "3:a",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    path], check=True)


def test_pipeline():
    from videolab import pipeline
    tmp = tempfile.mkdtemp(prefix="vl_test_")
    vid = os.path.join(tmp, "synthetic.mp4")
    make_video(vid)
    ctx = pipeline.run(vid, os.path.join(tmp, "runs"), no_asr=True, no_stems=True,
                       no_ocr=True)
    ev = json.load(open(os.path.join(ctx.run_dir, "evidence.json")))
    cuts = [(s["start"], s["cut_in"]["kind"], s["cut_in"]["transition"]) for s in ev["shots"][1:]]
    print("cuts:", cuts)
    print("motion:", [s["motion"]["type"] for s in ev["shots"]])
    print("scale:", [s["composition"]["shot_scale"] for s in ev["shots"]])
    assert len(ev["shots"]) >= 4, "应该至少检测到 4 个镜头"
    assert any(abs(t - 3) < 0.3 and "punch-in" in k for t, k, _ in cuts), "3s 处应是推镜"
    assert any(abs(t - 3) < 0.3 and tr == "硬切" for t, _, tr in cuts), "推镜是硬切，不是叠化"
    assert any(abs(t - 6) < 0.3 and k == "换镜头" and tr == "硬切" for t, k, tr in cuts), "6s 处应是普通硬切"
    assert any(abs(t - 9) < 0.3 and tr == "黑场淡入淡出" for t, _, tr in cuts), "9s 处应是黑场淡入"
    assert ev["shots"][-1]["motion"]["type"] == "推近", "mandelbrot 段应是推近"
    for f in ("report.md", "rhythm.png", "sheets/sheet_01.jpg"):
        assert os.path.exists(os.path.join(ctx.run_dir, f)), f
    print("✅ smoke test passed:", ctx.run_dir)


if __name__ == "__main__":
    test_pipeline()
