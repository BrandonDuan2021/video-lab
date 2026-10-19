"""每个切点：
  转场类型 —— 看切点前后 ±0.8s 的亮度和帧差曲线：硬切 / 叠化 / 黑场淡入淡出 / 闪白
  切法     —— 取切点前后各一帧做 ORB 特征匹配 + 相似变换：
              同一画面且没缩放 = 跳切；放大 = 推镜（punch-in）；缩小 = 拉镜；匹配不上 = 换镜头
"""
import cv2
import numpy as np

from ..config import AFPS, BOUNDARY_W
from ..util import grab_frame

ORB = cv2.ORB_create(800)
BF = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)


def transition_type(luma, diff, k):
    n = len(luma)
    lo, hi = max(0, k - 8), min(n, k + 9)
    L, D = luma[lo:hi], diff[lo:hi]
    if len(L) == 0:
        return "硬切"
    if L.min() < 12:
        return "黑场淡入淡出"
    if L.max() > 235 and L.max() > 1.6 * (np.median(L) + 1):
        return "闪白"
    # 叠化：切点“两侧”都有渐变（帧差抬升），各自和远处的基线比。
    # 只有一侧抬升（比如推镜后画面运动变快）不算叠化。
    def base(a, b):
        seg = diff[max(0, a):max(0, min(n, b))]
        return float(np.median(seg)) if len(seg) else 0.0
    bb, ba = base(k - 20, k - 9), base(k + 10, k + 21)
    before = int(np.sum(diff[max(0, k - 5):k] > 2 * bb + 2))
    after = int(np.sum(diff[k + 1:min(n, k + 6)] > 2 * ba + 2))
    return "叠化/软转场" if before >= 2 and after >= 2 else "硬切"


def cut_kind(a, b):
    if a is None or b is None:
        return "未知", {}
    ga, gb = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    ka, da = ORB.detectAndCompute(ga, None)
    kb, db = ORB.detectAndCompute(gb, None)
    if da is None or db is None or len(ka) < 30 or len(kb) < 30:
        return "换镜头", {"matches": 0}
    m = BF.match(da, db)
    if len(m) < 25:
        return "换镜头", {"matches": len(m)}
    pa = np.float32([ka[x.queryIdx].pt for x in m])
    pb = np.float32([kb[x.trainIdx].pt for x in m])
    M, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=4)
    ninl = int(inl.sum()) if inl is not None else 0
    if M is None or ninl < 20 or ninl < 0.3 * len(m):
        return "换镜头", {"matches": len(m), "inliers": ninl}
    scale = float(np.hypot(M[0, 0], M[1, 0]))
    info = {"matches": len(m), "inliers": ninl, "scale": round(scale, 3)}
    if scale > 1.08:
        return "推镜(punch-in)", info
    if scale < 0.92:
        return "拉镜(punch-out)", info
    return "跳切(同机位)", info


def run(ctx):
    luma, diff = ctx.frames["luma"], ctx.frames["hsv_diff"]
    for s in ctx.shots[1:]:
        c = s["start"]
        k = int(round(c * AFPS))
        a = grab_frame(ctx.path, c - 0.12, BOUNDARY_W)
        b = grab_frame(ctx.path, c + 0.12, BOUNDARY_W)
        kind, info = cut_kind(a, b)
        s["cut_in"] = {"transition": transition_type(luma, diff, k), "kind": kind,
                       "kind_detail": info}
        ctx.timeline.add("cut", c, transition=s["cut_in"]["transition"], cut_kind=kind)
    return f"{len(ctx.shots) - 1} 个切点"
