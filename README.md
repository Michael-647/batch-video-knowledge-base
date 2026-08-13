# Batch Video Knowledge Base / 批量视频知识库

[中文](#中文说明) · [English](#english)

Turn local video folders into a resumable, timestamped knowledge base with a three-tier subtitle strategy: embedded subtitles first, burned-in caption OCR second, and Faster-Whisper only for missing coverage.

将本地视频文件夹转换为可断点续跑、带时间戳的知识库。字幕处理遵循三级优先级：优先提取内嵌字幕，其次识别画面硬字幕，仅在缺失覆盖时使用 Faster-Whisper。

## 中文说明

### 功能特点

- 优先提取 SRT、ASS/SSA、WebVTT、mov_text 等内嵌文本字幕。
- 没有可用字幕轨时，通过 PaddleOCR 或 EasyOCR 识别画面硬字幕。
- OCR 覆盖不足时，仅使用 Faster-Whisper 补充不重叠的时间缺口。
- 为每个视频生成 SRT、TXT 和 Markdown 文件。
- 记录字幕来源、时间覆盖率、视频信息和带时间点的分段文本。
- 支持断点续跑、强制重建和固定分片处理。
- 默认在本地处理，不上传视频或转写内容。

### 支持格式

`MP4`、`MKV`、`MOV`、`WebM`、`AVI`、`M4V`

### 处理流程

```text
内嵌文本字幕
    ↓ 不可用
画面硬字幕 OCR
    ↓ 无结果或覆盖不足
Faster-Whisper 全量转写或缺口补充
    ↓
SRT + TXT + Markdown
    ↓
Codex 工作流生成 Excel 索引并执行质量抽检
```

### 运行要求

- Python 3.9+
- FFmpeg 和 FFprobe
- PaddleOCR（中文推荐）或 EasyOCR
- Faster-Whisper
- 本地 Faster-Whisper 模型目录；需要包含 `model.bin`

模型不包含在仓库中，需要单独准备。

### 安装为 Codex 技能

```powershell
git clone https://github.com/Michael-647/batch-video-knowledge-base.git `
  "$env:USERPROFILE\.codex\skills\batch-video-knowledge-base"
```

重新启动 Codex 或开启新任务，然后使用：

```text
使用 $batch-video-knowledge-base 处理 D:\videos
```

### 直接运行脚本

```powershell
python scripts/transcribe_videos.py "D:\videos" `
  --model "D:\models\faster-whisper-small"
```

调整 OCR 区域、采样间隔和覆盖率阈值：

```powershell
python scripts/transcribe_videos.py "D:\videos" `
  --model "D:\models\faster-whisper-small" `
  --ocr-region "0,0.50,1,0.50" `
  --ocr-interval 0.75 `
  --ocr-coverage-threshold 0.85
```

重新生成已有结果：

```powershell
python scripts/transcribe_videos.py "D:\videos" `
  --model "D:\models\faster-whisper-small" `
  --force
```

### 输出结构

```text
视频文件夹/
├─ 视频标题.mp4
└─ 本地知识库/
   ├─ 字幕/视频标题.srt
   ├─ 文本/视频标题.txt
   ├─ Markdown/视频标题.md
   └─ 知识库索引.xlsx
```

`transcribe_videos.py` 直接生成 SRT、TXT 和 Markdown。`知识库索引.xlsx` 由完整 Codex 技能工作流汇总和验证。

### 字幕来源标记

- `embedded:<language>:<codec>:stream-<index>`：内嵌文本字幕
- `ocr:paddleocr` / `ocr:easyocr`：OCR 达到覆盖率阈值
- `ocr:<engine>+whisper-gap-fill`：OCR 为主，Whisper 填补缺口
- `whisper`：没有可用内嵌字幕或 OCR 结果

时间覆盖率是字幕时间区间占视频时长的比例，是完整度诊断指标，不代表识别准确率。

### 注意事项

- 当前脚本只扫描指定目录的第一层，不递归扫描子目录。
- 图像字幕轨（如 PGS/DVD Subtitle）不会作为文本字幕提取，而会进入 OCR 流程。
- OCR 默认识别画面下方 50%，水印或界面文字可能需要通过调整区域排除。
- 本地文件修改时间不等同于视频平台发布时间。
- 请遵守视频内容、字幕、OCR 引擎及语音模型各自的许可证和使用条款。

---

## English

### Features

- Extracts usable embedded text tracks such as SRT, ASS/SSA, WebVTT, and mov_text first.
- Uses PaddleOCR or EasyOCR for burned-in captions when no text track is available.
- Runs Faster-Whisper only when OCR is unavailable, empty, or below the coverage threshold.
- Preserves OCR as the authoritative source and adds only Whisper segments that do not substantially overlap it.
- Generates SRT, plain-text transcripts, and timestamped Markdown notes for every video.
- Records subtitle source, timeline coverage, media metadata, and processing status.
- Supports resumable checkpoints, forced rebuilding, and deterministic sharding.
- Keeps processing local unless the user explicitly requests a cloud service.

### Supported formats

`MP4`, `MKV`, `MOV`, `WebM`, `AVI`, and `M4V`

### Processing pipeline

```text
Embedded text subtitle
    ↓ unavailable
Burned-in caption OCR
    ↓ empty or incomplete
Faster-Whisper transcription or gap filling
    ↓
SRT + TXT + Markdown
    ↓
Excel indexing and quality checks through the Codex workflow
```

### Requirements

- Python 3.9+
- FFmpeg and FFprobe
- PaddleOCR (recommended for Chinese) or EasyOCR
- Faster-Whisper
- A local Faster-Whisper model directory containing `model.bin`

Speech-recognition models are not included in this repository.

### Install as a Codex skill

```powershell
git clone https://github.com/Michael-647/batch-video-knowledge-base.git `
  "$env:USERPROFILE\.codex\skills\batch-video-knowledge-base"
```

Restart Codex or open a new task, then ask:

```text
Use $batch-video-knowledge-base to process D:\videos
```

### Run the script directly

```powershell
python scripts/transcribe_videos.py "D:\videos" `
  --model "D:\models\faster-whisper-small"
```

Tune the OCR region, sampling interval, and coverage threshold:

```powershell
python scripts/transcribe_videos.py "D:\videos" `
  --model "D:\models\faster-whisper-small" `
  --ocr-region "0,0.50,1,0.50" `
  --ocr-interval 0.75 `
  --ocr-coverage-threshold 0.85
```

Rebuild existing outputs:

```powershell
python scripts/transcribe_videos.py "D:\videos" `
  --model "D:\models\faster-whisper-small" `
  --force
```

### Output structure

```text
video-folder/
├─ video-title.mp4
└─ 本地知识库/
   ├─ 字幕/video-title.srt
   ├─ 文本/video-title.txt
   ├─ Markdown/video-title.md
   └─ 知识库索引.xlsx
```

`transcribe_videos.py` directly creates the SRT, TXT, and Markdown files. The formatted Excel index is assembled and verified by the full Codex skill workflow.

### Subtitle source labels

- `embedded:<language>:<codec>:stream-<index>`: extracted embedded text track
- `ocr:paddleocr` / `ocr:easyocr`: OCR met the configured coverage threshold
- `ocr:<engine>+whisper-gap-fill`: OCR remained authoritative while Whisper filled timeline gaps
- `whisper`: no usable embedded subtitle or OCR result was available

Timeline coverage is the union of subtitle time ranges divided by media duration. It is a completeness diagnostic, not an accuracy score.

### Notes

- The script scans only the top level of the selected directory; it does not recurse into subfolders.
- Image-based subtitle codecs such as PGS and DVD subtitles are not treated as text tracks and fall through to OCR.
- OCR defaults to the lower 50% of the frame. Adjust the region to avoid watermarks or UI text.
- Local file timestamps must not be treated as platform publication dates.
- Follow the licenses and terms that apply to the source videos, OCR engines, and speech-recognition models.
