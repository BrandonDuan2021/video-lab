"""全局参数。阈值都还没用真视频校准过，标了 UNCALIBRATED 的跑完第一批参考视频后要调。"""

AFPS = 10                 # 分析帧率
AW, AH = 320, 180         # 分析帧尺寸（颜色 / 光线统计）
FW, FH = 160, 90          # 光流尺寸
KEYFRAME_W = 640          # 关键帧宽度（构图 / OCR / 色板）
BOUNDARY_W = 320          # 切点前后帧宽度（跳切 / 推镜判断）

SHEET_COLS, SHEET_ROWS = 5, 4
TILE_W, TILE_H = 384, 216

# 内置切镜头（没装 PySceneDetect 时用）  UNCALIBRATED
BUILTIN_CUT_RATIO = 3.0       # 帧差是周围平均的几倍算切点
BUILTIN_CUT_MIN = 10.0        # 帧差绝对值下限（0-255）
MIN_SHOT_S = 0.5

# 运镜  UNCALIBRATED（单位：FW 宽度下 像素/帧）
MOTION_STATIC = 0.15
MOTION_ZOOM = 0.25
MOTION_JITTER = 1.2
EASE_RATIO = 0.6              # 首尾速度 < 中段 × 0.6 算缓入 / 缓出
PARALLAX_INDEX = 0.8

# 景别：人脸高度 / 画面高度  UNCALIBRATED
SCALE_BINS = [(0.45, "大特写"), (0.25, "特写"), (0.12, "近景"), (0.06, "中景"), (0.0, "全景")]
DOF_SHALLOW = 2.5             # 主体清晰度 / 边缘清晰度

# 切点对齐窗口（秒）
WIN_SENTENCE = (0.40, 0.15)   # 切点前 0.4s ~ 后 0.15s 内有句末
WIN_BEAT = 0.08
WIN_SFX = 0.06
ACTION_RATIO = 1.8            # 切点前 0.3s 运动强度 / 镜头中位运动强度
