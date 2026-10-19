# video-lab

把好视频拆开，量出它的节奏、运镜、光线和切点规律，再反推出“怎么拍、怎么剪”。另附一套自动粗剪的脚本。

```
测量层（analyze.py，确定性）   →  evidence.json + 关键帧联系表 + 节奏图
结论层（LLM，见 docs/）        →  风格总结 / 分镜配方 / 剪辑规则 / 布光推断 / 拍摄清单 / style_profile.json
对比（compare.py）             →  参考视频 vs 你的视频，差距排序
剪辑（edit/）                  →  素材体检 → shots.json → 渲染成片
```

## 安装（Mac, Apple Silicon）
```bash
brew install ffmpeg yt-dlp
pip3 install -r requirements.txt
```

## 用法
```bash
# 1. 分析一条参考视频（YouTube 链接或本地文件）
python3 analyze.py "https://youtu.be/VUZyZi1Wt1k"
#    纯音乐、没有口播的视频加 --no-asr

# 2. 把 runs/<名字>/ 交给 Claude，让它按 docs/CONCLUSIONS.md 出反向结论

# 3. 分析你自己的片，和参考视频对比
python3 analyze.py ~/Desktop/my_video.mp4
python3 compare.py runs/<参考>/evidence.json runs/<你的>/evidence.json
```

## 测量层能量出什么
| 项目 | 方法 | 可靠度 |
|---|---|---|
| 镜头切点 / 时长 | PySceneDetect AdaptiveDetector | 硬切很准，叠化和遮罩转场会漏 |
| 运镜（固定 / 横移 / 推拉 / 手持） | 10fps 光流：平均位移、发散度、抖动 | 中，大面积移动的主体会被误判成运镜 |
| 光线（亮度、对比度、主体与背景亮度比、色温、饱和度） | 逐帧统计 | 只是数字，灯放在哪靠结论层看图推断 |
| 语音（逐字时间戳、停顿、语速） | mlx-whisper / faster-whisper | 高 |
| 音乐节拍、音效位置 | librosa | 节奏清晰的音乐准 |
| 切点对齐（句末、词中间、节拍、音效） | 上面几项交叉比对 | 中到高 |

## 目录
```
analyze.py           测量层
compare.py           对比
docs/CONCLUSIONS.md  结论层的规则和输出格式
edit/                自动粗剪：inspect_footage.py → shots.json → render_edit.py
runs/                分析结果（不进 git）
```

## Roadmap
- [x] v1：切镜头、运镜、光线、语音、节拍、切点对齐、对比
- [ ] v2：结论层封装成 skill，自动读取 runs/ 出报告
- [ ] v3：style_profile.json 接入 edit/，按参考风格自动粗剪
