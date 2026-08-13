# Output format

## Per-video files

- `字幕/<video-stem>.srt`: final reconciled subtitle stream with millisecond timestamps.
- `文本/<video-stem>.txt`: final plain transcript in segment order.
- `Markdown/<video-stem>.md`: video metadata, subtitle source, coverage, full transcript, timestamped segments, and downstream knowledge placeholders.

The final directory contains `字幕/`, `文本/`, `Markdown/`, and `知识库索引.xlsx`. Temporary embedded subtitles, OCR frames, and JSON probe data must be deleted after each video.

## Subtitle source values

- `embedded:<language>:<codec>:stream-<index>`: extracted embedded text track; no OCR or Whisper used.
- `ocr:paddleocr` or `ocr:easyocr`: burned-in caption OCR met the coverage threshold.
- `ocr:<engine>+whisper-gap-fill`: OCR remained authoritative in covered spans; Whisper supplied non-overlapping gaps.
- `whisper`: neither embedded subtitles nor usable OCR results were available.

Coverage is the union of final segment time ranges divided by media duration. It is a diagnostic, not an accuracy score.

## Excel record

Create one row per source video:

```json
{
  "sequence": 1,
  "video_title": "视频标题",
  "video_filename": "视频标题.mp4",
  "video_path": "D:\\videos\\视频标题.mp4",
  "file_time": "2026-07-27 10:00:00",
  "publish_time": "",
  "duration_seconds": 60.0,
  "language": "zh",
  "subtitle_source": "ocr:paddleocr+whisper-gap-fill",
  "subtitle_coverage": 0.92,
  "segment_count": 20,
  "character_count": 500,
  "status": "成功",
  "srt_path": "D:\\videos\\本地知识库\\字幕\\视频标题.srt",
  "txt_path": "D:\\videos\\本地知识库\\文本\\视频标题.txt",
  "markdown_path": "D:\\videos\\本地知识库\\Markdown\\视频标题.md",
  "summary": "",
  "keywords": "",
  "topic": ""
}
```

Merge shards by `video_filename`, then sort naturally.
