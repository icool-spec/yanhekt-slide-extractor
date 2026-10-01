# YanheKT Slide Extractor

从延河课堂的独立课件视频中快速提取截图，不必等待整节回放播放完毕。

**已实测：** 一节约 49 分钟的回放，下载、抽帧和自动去重耗时约 4 分钟；1467 张采样图得到 37 张候选，经人工核对保留 26 张课件及视频示例截图。耗时取决于网络、机器和视频内容，不保证每节课都相同。

## 功能

- 读取已登录用户提供的 `VGA.m3u8` 播放清单。
- 4 路并发下载课件视频分段，用 FFmpeg 在本地抽帧。
- 根据画面稳定性和像素差异去重，保留采样原尺寸。
- 生成候选图集、缩略图和包含近似时间点的 JSON 报告。
- 用户核对后按编号排除桌面、黑屏等画面，生成顺序截图、HTML 图集和 ZIP。

输出是截图集，并非原始 PPT 文件。自动部分是抽帧和去重，非课件画面仍需用户核对。

## 安装

需要 Python 3.10 或更新版本。在 Windows、macOS 或 Linux 中：

```bash
git clone https://github.com/icool-spec/yanhekt-slide-extractor.git
cd yanhekt-slide-extractor
python -m venv .venv
```

Windows PowerShell 激活虚拟环境：

```powershell
.venv\Scripts\Activate.ps1
```

macOS / Linux：

```bash
source .venv/bin/activate
```

安装依赖：

```bash
python -m pip install -r requirements.txt
```

`imageio-ffmpeg` 在支持的平台上提供 FFmpeg，无需单独设置其路径。遇到未提供预编译程序的平台，可自行安装 FFmpeg 并设置 `IMAGEIO_FFMPEG_EXE`。

## 提取截图

1. 在浏览器中正常登录延河课堂，打开目标课程回放。
2. 打开开发者工具的 **网络 / Network** 面板，刷新并播放。
3. 在网络过滤框搜索 `m3u8`，找到 **VGA.m3u8** 请求。`Video1.m3u8` 通常是教室摄像头。
4. 复制完整请求 URL，包含签名参数，保存到项目外的私有文本文件中。

例如将地址保存为 `C:\private\course-url.txt`，运行：

```powershell
python yanhekt_extract.py --url-file 'C:\private\course-url.txt' --output output-course --interval 2
```

地址文件必须包含一行完整 HTTP(S) URL。签名会失效；遇到 HTTP 403，刷新回放并复制新地址。脚本不自动登录，不自动获取或续签媒体地址。

默认每 2 秒采样一次。首次运行请选择空的输出目录，避免已有截图混入。

## 核对与导出

打开 `output-course/candidates.html`，或查看 `contact_*.jpg`。找出需要排除的候选编号，例如 3 和 8：

```powershell
python yanhekt_finalize.py --output output-course --exclude 3,8 --title '我的课程课件截图'
```

没有需要排除的画面时省略 `--exclude`。导出前会检查编号是否有效，以及最终截图目录是否为空。

```text
output-course/
  samples/          全部采样帧
  candidates/       稳定画面去重候选
  candidates.html   候选图集
  contact_*.jpg     候选缩略图
  slides/           最终顺序截图
  index.html        最终图集
  slides.zip        截图及图集压缩包
  report.json       参数、时间点及排除记录
```

可以使用已有采样帧重新分析，不重新下载视频：

```bash
python yanhekt_extract.py --output output-course --analyze-only
```

重新分析使用报告中原来的采样间隔，不会重新采样。已有最终截图不会自动覆盖；再次导出时需先自行保留或移走旧的 `slides` 目录。

## 实现与限制

每张图缩小至 384×216 灰度图，比较平均像素差和大幅变化像素比例。连续至少两个相近样本视为稳定画面，选取中间样本，再与已保留截图比较以去重。

- 页面短暂显示或小幅内容变化可能遗漏，不能保证恢复全部原始课件页。
- 逐步展开的内容可能保留多张，嵌入视频可能保留静帧；截图数量不等于 PPT 页数。
- 仅支持已完成、无加密、连续的 MPEG-TS HLS media playlist。master playlist、初始化分段、字节范围和不连续分段尚未支持。
- 时间点是采样区间中心的近似值，不是精确的翻页时间。
- 目前处理时会下载完整课件视频分段；不是仅下载最后保留截图所需的数据。
- 已在 Windows、一个真实课程流上验证，其他系统与课程尚未实测。

仅处理自己有权访问的内容。签名 URL、登录信息、课程视频和截图属于本地运行数据；仓库只提供代码，`.gitignore` 已忽略常见媒体和输出文件。

## 检查

无需登录或访问真实课程：

```bash
python -m unittest discover -v
```

检查涵盖播放清单解析、不支持的布局、画面稳定性与去重、非默认采样间隔，以及导出图集和 ZIP 的完整性。

## License

MIT。许可证适用于本项目代码，不授权第三方课程素材。
