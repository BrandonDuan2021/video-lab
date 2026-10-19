# video-lab

把好视频拆开：先量出它的节奏、切法、运镜、构图、光线和声音，再反推出“怎么拍、怎么剪”。另附一套自动粗剪的脚本。

```
测量层（analyze.py → videolab/）  →  evidence.json + report.md + 关键帧联系表 + 节奏图
结论层（LLM，见 docs/）           →  风格总结 / 分镜配方 / 剪辑规则 / 布光推断 / 拍摄清单 / style_profile.json
对比（compare.py）                →  参考视频 vs 你的视频，差距排序
剪辑（edit/）                     →  素材体检 → shots.json → 渲染成片
```

架构和模块说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 安装（Mac, Apple Silicon）
```bash
brew install ffmpeg yt-dlp
pip3 install -r requirements.txt
pip3 install demucs whisperx      # 可选：分轨（闪避 / 音效）和更准的逐字时间戳
```
缺了哪个库就跳过哪一步，`report.md` 里会写明跳过了什么。

## 用法
```bash
python3 analyze.py "https://youtu.be/VUZyZi1Wt1k"     # 链接或本地文件
python3 analyze.py my.mp4 --no-stems                   # 不分轨，快很多
python3 compare.py runs/<参考>/evidence.json runs/<你的>/evidence.json
python3 tests/test_smoke.py                            # 冒烟测试（合成视频）
```
跑完把 `runs/<名字>/` 交给 Claude，让它按 [docs/CONCLUSIONS.md](docs/CONCLUSIONS.md) 出反向结论。

## 测量层量什么
| 维度 | 指标 | 方法 |
|---|---|---|
| 切镜头 | 切点、时长、分段节奏、开头 15s | PySceneDetect / 内置帧差，加光流突变补检 |
| 转场 | 硬切 / 叠化 / 黑场 / 闪白 | 切点前后的亮度和帧差曲线 |
| 切法 | 跳切 / 推镜 / 拉镜 / 换镜头 | 切点前后两帧做 ORB 匹配，再估计相似变换 |
| 切点对齐 | 句末、词中间、停顿、声音跨切点（J/L）、节拍、音效、动作 | 融合层查时间轴 |
| 运镜 | 类型、速度、缓入缓出、视差、滚转、抖动 | 10fps 光流 |
| 构图 | 景别、主体位置、头顶留白、景深、对称度 | Haar 人脸 + 清晰度图 |
| 光线色彩 | 亮度、对比、分位数、色温、饱和度、色板、调色一致性、主光方向和光比 | 逐帧统计 + k-means + 人脸左右亮度 |
| 屏幕文字 | 哪些镜头有字、写了什么 | ocrmac（Apple Vision） |
| 声音 | 语速、停顿、节拍、音效密度、闪避 dB、响度 LUFS、B-roll 覆盖率 | demucs + whisper + librosa + pyloudnorm |

所有阈值都还没用真视频校准过（见 `videolab/config.py`），跑完第一批参考视频后要调。

## Roadmap
- [x] v1：单文件版本
- [x] v2：模块化流水线（单次解码 + 帧消费者）、切法 / 转场 / 构图 / 色彩 / 声音分轨 / 融合层
- [ ] 用 3–5 条参考视频校准阈值
- [ ] TransNetV2 作为第二个切镜头后端，跟现有结果交叉验证
- [ ] 结论层封装成 skill
- [ ] style_profile.json 接入 edit/，按参考风格自动粗剪
