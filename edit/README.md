# 骑车视频自动剪辑 POC：回家照做

## 0. 一次性安装（2 分钟）
```bash
brew install ffmpeg
pip3 install opencv-python numpy librosa
```

## 1. 放素材
- 把 GoPro 素材全拷到 `~/Desktop/bike_clips/`。剪的是这里的拷贝，SD 卡原片不会动。
- 配乐也放进去，命名为 `music.mp3`。要用免版权音乐，比如 YouTube Audio Library 或 Pixabay Music。vibe 片选 90–110 BPM、鼓点清楚的 lo-fi 或 chill 曲子最好卡点。

## 2. 体检素材（只看不剪）
```bash
python3 ~/Desktop/bike_edit/inspect_footage.py ~/Desktop/bike_clips
```
跑完会生成 `bike_clips/_inspect/` 文件夹，里面有每段素材的联系表图片和一份 report.json。

## 3. 让 Claude 看素材、写剪辑表
回到这个对话说一声“素材体检好了”，并把 `Desktop` 文件夹的权限给我。
我会看联系表和每秒分数，挑镜头、排故事线（出发 → 骑行 → 风景 → 收尾），然后写出 `shots.json`。

## 4. 渲染
```bash
python3 ~/Desktop/bike_edit/render_edit.py ~/Desktop/bike_clips/shots.json
```
成片输出到 `~/Desktop/bike_vlog.mp4`。

## 5. 改一轮
看完把感受告诉我，比如“开头太慢”“第 5 个镜头换掉”“再多点慢放”。我改 `shots.json`，你再跑一次第 4 步。

## 怎么让它显得专业（拍了的素材用得上的话）
- 慢放：GoPro 用 60/120fps 拍的车轮、踩踏、头发被风吹的镜头，放到 0.5x，vibe 感最强。
- 低机位贴地拍车经过、跟拍背影、第一视角，这几种轮流穿插，别连着用同一种。
- 镜头长度 2–4 秒，跟着节拍切。
- 全片统一一个调色。
