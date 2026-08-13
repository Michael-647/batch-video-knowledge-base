from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
TEXT_SUBTITLE_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}
def natural_key(path: Path) -> list[Any]:
    return [int(x) if x.isdigit() else x.casefold() for x in re.split(r"(\d+)", path.name)]


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, check=check)


def srt_time(seconds: float) -> str:
    value = max(0, round(seconds * 1000))
    hours, value = divmod(value, 3_600_000)
    minutes, value = divmod(value, 60_000)
    secs, millis = divmod(value, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def clock(seconds: float) -> str:
    value = max(0, round(seconds))
    hours, value = divmod(value, 3600)
    minutes, secs = divmod(value, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_srt_time(value: str) -> float:
    match = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)", value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value}")
    hours, minutes, seconds, fraction = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(fraction) / (10 ** len(fraction))


def clean_subtitle_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{\\[^}]+}", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_srt(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    segments: list[dict[str, Any]] = []
    timestamp = re.compile(r"(\d{1,3}:\d{2}:\d{2}[,.]\d+)\s*-->\s*(\d{1,3}:\d{2}:\d{2}[,.]\d+)")
    for block in re.split(r"\n\s*\n", content):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        time_index = next((i for i, line in enumerate(lines) if timestamp.search(line)), None)
        if time_index is None:
            continue
        match = timestamp.search(lines[time_index])
        assert match
        text = clean_subtitle_text(" ".join(lines[time_index + 1:]))
        if text:
            segments.append({"start": parse_srt_time(match.group(1)), "end": parse_srt_time(match.group(2)), "text": text})
    return segments


def probe_media(video: Path, ffprobe: str) -> dict[str, Any]:
    result = run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)])
    data = json.loads(result.stdout)
    duration = float(data.get("format", {}).get("duration") or 0)
    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "duration": duration,
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "subtitle_streams": [s for s in data.get("streams", []) if s.get("codec_type") == "subtitle"],
    }


def choose_subtitle_stream(streams: list[dict[str, Any]], preferred: list[str]) -> list[dict[str, Any]]:
    def rank(stream: dict[str, Any]) -> tuple[int, int]:
        language = str(stream.get("tags", {}).get("language", "")).casefold()
        codec = str(stream.get("codec_name", "")).casefold()
        language_rank = next((i for i, item in enumerate(preferred) if item == language), len(preferred))
        codec_rank = 0 if codec in TEXT_SUBTITLE_CODECS else 1
        return language_rank, codec_rank
    return sorted(streams, key=rank)


def extract_embedded_subtitles(
    video: Path,
    streams: list[dict[str, Any]],
    preferred: list[str],
    ffmpeg: str,
    temp_dir: Path,
) -> tuple[list[dict[str, Any]], str] | None:
    for stream in choose_subtitle_stream(streams, preferred):
        codec = str(stream.get("codec_name", "unknown"))
        if codec.casefold() not in TEXT_SUBTITLE_CODECS:
            continue
        index = int(stream["index"])
        language = str(stream.get("tags", {}).get("language", "und"))
        extracted = temp_dir / f"embedded-{index}.srt"
        command = [ffmpeg, "-y", "-v", "error", "-i", str(video), "-map", f"0:{index}", "-c:s", "srt", str(extracted)]
        result = run(command, check=False)
        if result.returncode == 0 and extracted.exists():
            segments = parse_srt(extracted)
            if segments:
                return segments, f"embedded:{language}:{codec}:stream-{index}"
    return None


def collect_ocr_pairs(value: Any) -> list[tuple[str, float]]:
    pairs: list[tuple[str, float]] = []
    if value is None:
        return pairs
    if hasattr(value, "json"):
        raw_json = value.json() if callable(value.json) else value.json
        if raw_json is not value:
            return collect_ocr_pairs(raw_json)
    if isinstance(value, dict):
        texts = value.get("rec_texts") or value.get("texts")
        scores = value.get("rec_scores") or value.get("scores") or []
        if texts:
            for i, text in enumerate(texts):
                score = float(scores[i]) if i < len(scores) else 1.0
                pairs.append((str(text), score))
            return pairs
        for child in value.values():
            pairs.extend(collect_ocr_pairs(child))
        return pairs
    if isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], (int, float)):
            return [(value[0], float(value[1]))]
        if len(value) == 2 and isinstance(value[1], (list, tuple)) and len(value[1]) >= 2 and isinstance(value[1][0], str):
            return [(value[1][0], float(value[1][1]))]
        for child in value:
            pairs.extend(collect_ocr_pairs(child))
    return pairs


def build_ocr_engine(name: str, language: str, min_confidence: float) -> tuple[str, Callable[[Path], str]]:
    errors = []
    if name in {"auto", "paddleocr"}:
        try:
            from paddleocr import PaddleOCR  # type: ignore
            try:
                engine = PaddleOCR(lang=language, use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, show_log=False)
                if hasattr(engine, "predict"):
                    predict = lambda path: engine.predict(str(path))
                else:
                    predict = lambda path: engine.ocr(str(path), cls=False)
            except TypeError:
                engine = PaddleOCR(lang=language, use_angle_cls=False, show_log=False)
                predict = lambda path: engine.ocr(str(path), cls=False)

            def paddle(path: Path) -> str:
                pairs = collect_ocr_pairs(predict(path))
                return clean_subtitle_text(" ".join(text for text, score in pairs if score >= min_confidence))
            return "paddleocr", paddle
        except Exception as error:
            errors.append(f"PaddleOCR: {error}")
            if name == "paddleocr":
                raise RuntimeError("; ".join(errors)) from error
    if name in {"auto", "easyocr"}:
        try:
            import easyocr  # type: ignore
            languages = ["ch_sim", "en"] if language in {"ch", "zh", "chinese"} else [language, "en"]
            reader = easyocr.Reader(languages, gpu=False)

            def easy(path: Path) -> str:
                rows = reader.readtext(str(path), detail=1, paragraph=False)
                return clean_subtitle_text(" ".join(str(row[1]) for row in rows if float(row[2]) >= min_confidence))
            return "easyocr", easy
        except Exception as error:
            errors.append(f"EasyOCR: {error}")
    raise RuntimeError("No usable OCR engine. Install paddleocr or easyocr. " + "; ".join(errors))


def parse_region(value: str) -> tuple[float, float, float, float]:
    try:
        x, y, width, height = (float(item) for item in value.split(","))
    except Exception as error:
        raise argparse.ArgumentTypeError("OCR region must be x,y,width,height fractions") from error
    if min(x, y, width, height) < 0 or x + width > 1 or y + height > 1 or width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("OCR region fractions must stay inside the frame")
    return x, y, width, height


def extract_ocr_subtitles(
    video: Path,
    media: dict[str, Any],
    ffmpeg: str,
    engine_name: str,
    language: str,
    min_confidence: float,
    interval: float,
    region: tuple[float, float, float, float],
    temp_dir: Path,
) -> tuple[list[dict[str, Any]], str]:
    width, height = media["width"], media["height"]
    if width <= 0 or height <= 0:
        return [], engine_name
    # Resolve the OCR dependency before extracting potentially thousands of
    # temporary frames, so a missing engine fails fast and falls back cleanly.
    label, recognize = build_ocr_engine(engine_name, language, min_confidence)
    x, y, crop_width, crop_height = region
    px = int(width * x) // 2 * 2
    py = int(height * y) // 2 * 2
    pw = max(2, int(width * crop_width) // 2 * 2)
    ph = max(2, int(height * crop_height) // 2 * 2)
    frame_dir = temp_dir / "ocr-frames"
    frame_dir.mkdir()
    pattern = frame_dir / "%08d.jpg"
    command = [
        ffmpeg, "-y", "-v", "error", "-i", str(video),
        "-vf", f"fps=1/{interval},crop={pw}:{ph}:{px}:{py}", "-q:v", "3", str(pattern),
    ]
    result = run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg frame extraction failed: {result.stderr.strip()}")
    observations: list[tuple[float, str]] = []
    for i, frame in enumerate(sorted(frame_dir.glob("*.jpg")), start=0):
        observations.append((round(i * interval, 3), recognize(frame)))

    segments: list[dict[str, Any]] = []
    current_text = ""
    current_start = 0.0
    current_end = 0.0
    for timestamp, text in observations:
        if not text:
            continue
        similarity = difflib.SequenceMatcher(None, current_text, text).ratio() if current_text else 0
        if current_text and similarity >= 0.82 and timestamp <= current_end + interval * 2.1:
            if len(text) > len(current_text):
                current_text = text
            current_end = timestamp + interval
            continue
        if current_text:
            segments.append({"start": current_start, "end": min(current_end, media["duration"]), "text": current_text})
        current_text, current_start, current_end = text, timestamp, timestamp + interval
    if current_text:
        segments.append({"start": current_start, "end": min(current_end, media["duration"]), "text": current_text})
    return segments, label


def segment_coverage(segments: list[dict[str, Any]], duration: float) -> float:
    if not segments or duration <= 0:
        return 0.0
    intervals = sorted((max(0.0, s["start"]), min(duration, s["end"])) for s in segments)
    total = 0.0
    start, end = intervals[0]
    for next_start, next_end in intervals[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += max(0, end - start)
            start, end = next_start, next_end
    total += max(0, end - start)
    return min(1.0, total / duration)


def overlap_ratio(segment: dict[str, Any], primary: list[dict[str, Any]]) -> float:
    length = max(0.001, segment["end"] - segment["start"])
    overlap = sum(max(0.0, min(segment["end"], item["end"]) - max(segment["start"], item["start"])) for item in primary)
    return min(1.0, overlap / length)


def merge_with_whisper(primary: list[dict[str, Any]], whisper: list[dict[str, Any]]) -> list[dict[str, Any]]:
    supplement = [item for item in whisper if overlap_ratio(item, primary) < 0.25]
    return sorted(primary + supplement, key=lambda item: (item["start"], item["end"]))


class WhisperTranscriber:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.pipeline = None

    def transcribe(self, video: Path) -> tuple[list[dict[str, Any]], str, str]:
        if self.args.model is None:
            raise RuntimeError("Whisper fallback is required, but --model was not provided")
        model_dir = self.args.model.resolve()
        if not (model_dir / "model.bin").is_file():
            raise RuntimeError(f"Invalid Faster-Whisper model: {model_dir}")
        if self.pipeline is None:
            from faster_whisper import BatchedInferencePipeline, WhisperModel  # type: ignore
            model = WhisperModel(str(model_dir), device="cpu", compute_type="int8", cpu_threads=self.args.cpu_threads)
            self.pipeline = BatchedInferencePipeline(model=model)
        raw, info = self.pipeline.transcribe(
            str(video), batch_size=self.args.batch_size, language=self.args.language,
            task="transcribe", beam_size=self.args.beam_size, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500}, condition_on_previous_text=False,
        )
        segments = [
            {"start": round(x.start, 3), "end": round(x.end, 3), "text": x.text.strip()}
            for x in raw if x.text.strip()
        ]
        return segments, info.language or self.args.language, model_dir.name


def write_outputs(
    video: Path,
    knowledge: Path,
    media_seconds: float,
    language: str,
    segments: list[dict[str, Any]],
    method: str,
    model_label: str,
    coverage: float,
) -> tuple[Path, Path, Path, str]:
    srt_path = knowledge / "字幕" / f"{video.stem}.srt"
    txt_path = knowledge / "文本" / f"{video.stem}.txt"
    md_path = knowledge / "Markdown" / f"{video.stem}.md"
    transcript = "\n".join(item["text"] for item in segments).strip()
    srt_blocks = [
        f"{i}\n{srt_time(item['start'])} --> {srt_time(item['end'])}\n{item['text']}"
        for i, item in enumerate(segments, start=1)
    ]
    srt_path.write_text("\n\n".join(srt_blocks) + ("\n" if srt_blocks else ""), encoding="utf-8-sig")
    txt_path.write_text(transcript + ("\n" if transcript else ""), encoding="utf-8-sig")
    file_time = datetime.fromtimestamp(video.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    markdown = [
        f"# {video.stem}", "", "## 视频信息", "", f"- 视频标题：{video.stem}",
        f"- 原视频文件：`{video}`", f"- 本地文件时间：{file_time}",
        "- 发布时间：未从当前文件中取得平台官方发布时间", f"- 视频时长：{clock(media_seconds)}",
        f"- 字幕生成方式：{method}", f"- 字幕时间覆盖率：{coverage:.1%}", f"- 识别语言：{language}",
        f"- 识别模型：{model_label or '未使用语音模型'}", "", "## 完整转写文本", "",
        transcript or "（未识别到有效字幕或语音）", "", "## 带时间点的分段字幕", "",
    ]
    markdown.extend(f"- [{clock(item['start'])} → {clock(item['end'])}] {item['text']}" for item in segments)
    if not segments:
        markdown.append("- （未识别到有效字幕或语音）")
    markdown.extend(["", "## 后续知识整理", "", "- 摘要：待生成", "- 关键词：待生成", "- 主题分类：待生成", ""])
    md_path.write_text("\n".join(markdown), encoding="utf-8-sig")
    return srt_path, txt_path, md_path, transcript


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract subtitles with priority: embedded track, OCR, then Whisper")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument("--model", type=Path, help="Faster-Whisper model directory; required only when Whisper fallback runs")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--cpu-threads", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--beam-size", type=int, default=1)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--subtitle-languages", default="zh,zho,chi,chs,und")
    parser.add_argument("--ocr-engine", choices=("auto", "paddleocr", "easyocr", "none"), default="auto")
    parser.add_argument("--ocr-language", default="ch")
    parser.add_argument("--ocr-region", type=parse_region, default=parse_region("0,0.50,1,0.50"))
    parser.add_argument("--ocr-interval", type=float, default=0.75)
    parser.add_argument("--ocr-min-confidence", type=float, default=0.55)
    parser.add_argument("--ocr-coverage-threshold", type=float, default=0.85)
    parser.add_argument("--no-whisper-gap-fill", action="store_true")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument("--ffprobe", default=shutil.which("ffprobe") or "ffprobe")
    args = parser.parse_args()

    video_dir = args.video_dir.resolve()
    if not video_dir.is_dir():
        print("Video directory is invalid.", file=sys.stderr)
        return 2
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        print("Invalid shard configuration.", file=sys.stderr)
        return 2
    if args.ocr_interval <= 0 or not 0 <= args.ocr_min_confidence <= 1 or not 0 <= args.ocr_coverage_threshold <= 1:
        print("Invalid OCR interval, confidence, or coverage threshold.", file=sys.stderr)
        return 2

    knowledge = video_dir / "本地知识库"
    for name in ("字幕", "文本", "Markdown"):
        (knowledge / name).mkdir(parents=True, exist_ok=True)
    all_videos = sorted([p for p in video_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS], key=natural_key)
    assigned = [(i, video) for i, video in enumerate(all_videos, start=1) if (i - 1) % args.shard_count == args.shard_index]
    if not assigned:
        print("No supported video files found.", file=sys.stderr)
        return 1

    preferred = [item.strip().casefold() for item in args.subtitle_languages.split(",") if item.strip()]
    if args.model is not None:
        # Load CTranslate2's native DLLs before Paddle mutates the process DLL search state on Windows.
        from faster_whisper import BatchedInferencePipeline, WhisperModel  # type: ignore  # noqa: F401
    whisper = WhisperTranscriber(args)
    failures = 0
    for shard_pos, (_, video) in enumerate(assigned, start=1):
        expected = [knowledge / "字幕" / f"{video.stem}.srt", knowledge / "文本" / f"{video.stem}.txt", knowledge / "Markdown" / f"{video.stem}.md"]
        if not args.force and all(path.exists() for path in expected):
            print(f"[{shard_pos}/{len(assigned)}] skip {video.name}", flush=True)
            continue
        print(f"[{shard_pos}/{len(assigned)}] inspect {video.name}", flush=True)
        try:
            media = probe_media(video, args.ffprobe)
            segments: list[dict[str, Any]] = []
            language = args.language
            method = ""
            model_label = ""
            with tempfile.TemporaryDirectory(prefix="video-subtitle-") as temp:
                temp_dir = Path(temp)
                embedded = extract_embedded_subtitles(video, media["subtitle_streams"], preferred, args.ffmpeg, temp_dir)
                if embedded:
                    segments, method = embedded
                    language = method.split(":", 2)[1]
                else:
                    ocr_segments: list[dict[str, Any]] = []
                    ocr_label = ""
                    if args.ocr_engine != "none":
                        try:
                            ocr_segments, ocr_label = extract_ocr_subtitles(
                                video, media, args.ffmpeg, args.ocr_engine, args.ocr_language,
                                args.ocr_min_confidence, args.ocr_interval, args.ocr_region, temp_dir,
                            )
                        except Exception as error:
                            print(f"OCR unavailable for {video.name}: {error}; falling back to Whisper", file=sys.stderr, flush=True)
                    ocr_coverage = segment_coverage(ocr_segments, media["duration"])
                    if ocr_segments and (ocr_coverage >= args.ocr_coverage_threshold or args.no_whisper_gap_fill):
                        segments, method = ocr_segments, f"ocr:{ocr_label}"
                    elif ocr_segments:
                        whisper_segments, language, model_label = whisper.transcribe(video)
                        segments = merge_with_whisper(ocr_segments, whisper_segments)
                        method = f"ocr:{ocr_label}+whisper-gap-fill"
                    else:
                        segments, language, model_label = whisper.transcribe(video)
                        method = "whisper"
            coverage = segment_coverage(segments, media["duration"])
            write_outputs(video, knowledge, media["duration"], language, segments, method, model_label, coverage)
            print(f"[{shard_pos}/{len(assigned)}] done source={method} coverage={coverage:.1%}", flush=True)
        except Exception as error:
            failures += 1
            print(f"FAILED {video.name}: {error}", file=sys.stderr, flush=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
