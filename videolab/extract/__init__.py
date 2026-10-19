"""提取器注册表。
FRAME_CONSUMERS：单次解码时逐帧跑的（只算数，不存帧）
STEPS：解码之后按顺序跑的步骤 (名字, 模块)。顺序有依赖：
  shots → keyframes → transitions / motion / composition → color（要用人脸框）→ ocr → audio
新加一个维度 = 写一个模块，有 run(ctx)，往 ctx.shots 或 ctx.timeline 写数据，再登记到这里。
"""
from . import audio, color, composition, keyframes, motion, ocr, shots, transitions


def frame_consumers():
    return [shots.DiffConsumer(), motion.FlowConsumer(), color.StatsConsumer()]


STEPS = [
    ("切镜头", shots),
    ("关键帧", keyframes),
    ("转场 + 切法", transitions),
    ("运镜", motion),
    ("构图", composition),
    ("光线色彩", color),
    ("屏幕文字", ocr),
    ("声音", audio),
]
