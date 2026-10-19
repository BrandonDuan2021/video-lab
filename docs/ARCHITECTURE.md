# 架构

```
analyze.py                 facade：解析参数 → pipeline.run()
videolab/
  pipeline.py              编排：fetch → 单次解码 → 提取步骤 → 融合 → 输出
  fetch.py                 本地文件 / yt-dlp 下载
  decode.py                只解码一次：10fps 低清帧流逐帧喂给“帧消费者”；抽音频
  model.py                 Context（流水线上下文）、Timeline（事件时间轴）
  config.py                所有阈值（标了 UNCALIBRATED 的要用真视频校准）
  extract/
    __init__.py            注册表：帧消费者 + 步骤顺序
    shots.py               切镜头（PySceneDetect 或内置）+ 光流突变补检推镜 / 跳切
    keyframes.py           每镜头中间帧
    transitions.py         转场类型（硬切 / 叠化 / 黑场 / 闪白）+ 切法（跳切 / 推镜 / 拉镜 / 换镜头）
    motion.py              运镜类型、速度、缓入缓出、视差、滚转、抖动
    composition.py         人脸 → 景别、主体位置、头顶留白、景深、对称度
    color.py               光线统计、色板、Lab 平均、主光方向和光比
    ocr.py                 屏幕文字（Mac / ocrmac）
    audio.py               分轨（demucs）、转录（whisperx / mlx-whisper / faster-whisper）、
                           节拍、起音、音效候选、闪避、响度
  fuse.py                  融合层：切点 × 时间轴 → 句末 / 词中 / 停顿 / J-L cut / 卡拍 / 音效 / 动作上切；汇总
  report.py                evidence.json、report.md、sheets/、rhythm.png
```

## 两种核心数据

- **镜头表** `ctx.shots`：每个镜头一个 dict，各提取器往里加字段。
- **事件时间轴** `ctx.timeline`：带时间戳的事件。`kind` 有 `cut`、`word`、`sentence_end`、`pause`、`beat`、`onset`、`sfx`、`text`。

融合层只读这两样东西，所以提取器之间互不依赖。只有一处例外：`color` 要用 `composition` 产出的人脸框。

## 加一个新维度

1. 在 `extract/` 写一个模块，提供 `run(ctx)`，往 `ctx.shots[i]` 或 `ctx.timeline` 写数据。
2. 如果要逐帧算数，再写一个 `FrameConsumer`，在 `frame_consumers()` 里登记，它会搭上同一次解码。
3. 在 `STEPS` 里放到合适的位置。
4. 想进汇总的话，在 `fuse.summarize` 里加一行。

## 可选依赖

缺了哪个库，就跳过哪一步，并把原因写进 `evidence.json` 的 `skipped` 和 `report.md`。结论层看到跳过的步骤，不会基于缺失的数据下结论。

## 已知局限

- 阈值都没有用真视频校准过。
- Haar 人脸检测会漏侧脸；OpenCV 5.0 没有 Haar，需要用 4.x。
- 景别分类只对有人脸的镜头有效，没人脸的镜头交给结论层看图判断。
- 音效检测是近似的：强起音点、又不在节拍上，就算一个音效。
- J/L-cut 只能检测出“声音跨过切点”，分不出是 J 还是 L，因为不知道声音属于哪个镜头。
- `lab_mean` 是 OpenCV 的 8 位 Lab：L 取值 0–255，a/b 以 128 为中性。
