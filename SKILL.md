---
name: batch-video-knowledge-base
description: Batch-extract subtitles from local video folders with a three-tier priority—embedded subtitle tracks first, burned-in caption OCR second, and Faster-Whisper only for missing coverage—then create SRT, TXT, Markdown knowledge notes, and a formatted Excel index. Use when Codex needs accurate subtitles or transcripts from MP4/MKV/MOV/WebM/AVI/M4V files, a resumable local video knowledge base, or timestamped video content organized for downstream knowledge extraction.
---

# Batch Video Knowledge Base

Build a resumable local video knowledge base. Keep all processing local unless the user explicitly requests a cloud service.

## Subtitle priority

Use `scripts/transcribe_videos.py` and preserve this order:

1. Extract a usable embedded text subtitle track with FFprobe/FFmpeg. Do not run OCR or Whisper when this succeeds.
2. If no usable text track exists, OCR burned-in captions from the configured frame region. Prefer PaddleOCR; fall back to EasyOCR.
3. If OCR is unavailable, empty, or below the coverage threshold, use Faster-Whisper. When OCR has partial coverage, retain OCR text and add only Whisper segments that do not substantially overlap it.

Record the selected source and final time coverage in each Markdown file. Never describe OCR or Whisper output as the platform's original subtitle track.

## Workflow

1. Resolve and validate:
   - source video directory;
   - FFmpeg and FFprobe executables;
   - Python 3.9+ environment;
   - PaddleOCR or EasyOCR for burned-in captions;
   - local Faster-Whisper model containing `model.bin` when fallback may run.
2. Inventory video count, size, duration, existing outputs, CPU/RAM, and usable GPU runtime before writing.
3. Keep source videos in place and create:

```text
视频文件夹/
├─ 视频标题.mp4
└─ 本地知识库/
   ├─ 字幕/视频标题.srt
   ├─ 文本/视频标题.txt
   ├─ Markdown/视频标题.md
   └─ 知识库索引.xlsx
```

4. Do not retain persistent JSON or extracted OCR frames. Match every SRT/TXT/Markdown filename to the video stem.
5. Start sequentially. Shard only when workload and RAM justify multiple model or OCR instances.
6. Treat each complete SRT+TXT+Markdown set as a resumable checkpoint. Use `--force` when replacing older Whisper-only outputs.
7. Generate `知识库索引.xlsx` with the spreadsheets skill. Include source method, coverage, duration, status, character/segment counts, paths, summary, keywords, and topic. Verify and render every sheet.
8. Sample the first, middle, and last outputs plus at least one result from each source method actually used.

## Commands

Default three-tier extraction:

```powershell
python scripts/transcribe_videos.py "D:\videos" --model "D:\models\faster-whisper-small"
```

Replace existing Whisper-only files:

```powershell
python scripts/transcribe_videos.py "D:\videos" --model "D:\models\faster-whisper-small" --force
```

Tune the lower-half OCR region and sampling:

```powershell
python scripts/transcribe_videos.py "D:\videos" --model "D:\models\faster-whisper-small" --ocr-region "0,0.50,1,0.50" --ocr-interval 0.75 --ocr-coverage-threshold 0.85
```

For two shards, keep the shard count fixed and use unique indexes:

```powershell
python scripts/transcribe_videos.py "D:\videos" --model "D:\models\faster-whisper-small" --shard-count 2 --shard-index 0
python scripts/transcribe_videos.py "D:\videos" --model "D:\models\faster-whisper-small" --shard-count 2 --shard-index 1
```

## Runtime rules

- Prefer embedded text tracks over all recognition results, including ASS/SSA, WebVTT, mov_text, and SubRip.
- Treat image subtitle codecs such as PGS/DVD subtitles as unusable text tracks and continue to frame OCR.
- Default OCR to the lower 50% of the frame. Adjust `--ocr-region x,y,width,height` when captions occupy another area.
- Prefer PaddleOCR for Chinese. EasyOCR is an optional fallback.
- Use `small`, CPU `int8`, VAD, and `beam_size=1` as the stable Chinese Whisper fallback defaults.
- On 8 GB RAM, run at most two `small` Whisper processes; OCR model memory may require sequential execution.
- Do not claim the local file timestamp is the platform publish time.
- Preserve UTF-8 with BOM for Windows-facing SRT, TXT, and Markdown.

## Verification

- Confirm video/SRT/TXT/Markdown counts match.
- Confirm every Markdown file contains `字幕生成方式` and `字幕时间覆盖率`.
- For embedded results, compare several lines with the extracted subtitle track.
- For OCR results, visually compare sampled captions and check watermark/UI text was not included.
- For `ocr+whisper-gap-fill`, confirm Whisper text appears only in OCR gaps.
- Explain every failed or empty record; never silently fall back without recording the source method.

Read [references/output-format.md](references/output-format.md) when changing fields or downstream integrations.
