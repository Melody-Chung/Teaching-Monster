import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw

MIN_AUDIO_SAMPLE_RATE = 16_000
MIN_VIDEO_HEIGHT = 720
MAX_VIDEO_DURATION_SECONDS = 30 * 60
MAX_VIDEO_SIZE_BYTES = 3 * 1024 * 1024 * 1024
MAX_SUPPORTING_FILES_BYTES = 100 * 1024 * 1024
MAX_SUPPLEMENTARY_FILES = 5
TTS_MAX_CHARS_PER_CHUNK = 1200
SLIDESHOW_FPS = 4


def ensure_command_available(command_name: str):
    if shutil.which(command_name) is None:
        raise RuntimeError(f"The '{command_name}' command is not available in the current environment.")


def file_size_bytes(file_path: str) -> int:
    return Path(file_path).stat().st_size


def total_size_bytes(paths: list[str]) -> int:
    return sum(file_size_bytes(path) for path in paths if Path(path).exists())


def normalize_voiceover_text(script_text: str | None) -> str:
    raw_text = "" if script_text is None else str(script_text)
    text = unicodedata.normalize("NFKC", raw_text)
    replacements = {
        "**": "",
        "??": " - ",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "—": "-",
        "–": "-",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)

    text = re.sub(r"[^\x09\x0A\x0D\x20-\x7E]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("m/s^2", "meters per second squared")
    text = text.replace("m/s²", "meters per second squared")
    text = text.replace("m/s簡", "meters per second squared")
    text = text.replace("kg*m/s^2", "kilogram meters per second squared")
    text = text.replace("kg m/s^2", "kilogram meters per second squared")
    return text


def split_tts_text(script_text: str | None, max_chars: int = TTS_MAX_CHARS_PER_CHUNK) -> list[str]:
    script_text = "" if script_text is None else str(script_text)
    if len(script_text) <= max_chars:
        return [script_text]

    sentences = re.split(r"(?<=[.!?])\s+", script_text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if len(sentence) > max_chars:
            words = sentence.split()
            word_chunk = ""
            for word in words:
                candidate = f"{word_chunk} {word}".strip()
                if len(candidate) <= max_chars:
                    word_chunk = candidate
                else:
                    if word_chunk:
                        chunks.append(word_chunk)
                    word_chunk = word
            if word_chunk:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(word_chunk)
            continue

        candidate = f"{current} {sentence}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)

    return chunks or [script_text]


def run_edge_tts(text_path: str, output_audio_path: str, timeout_seconds: int, max_attempts: int = 5) -> None:
    command = [
        "edge-tts",
        "--voice",
        "en-US-ChristopherNeural",
        "-f",
        text_path,
        "--write-media",
        output_audio_path,
    ]

    last_exc: subprocess.CalledProcessError | subprocess.TimeoutExpired | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
            )
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            last_exc = exc
            if attempt == max_attempts:
                break
            time.sleep(min(4 * attempt, 12))

    if last_exc is not None:
        raise last_exc


def concat_audio_files(audio_paths: list[str], output_audio_path: str, timeout_seconds: int = 600) -> str:
    ensure_command_available("ffmpeg")

    concat_list_path = Path(output_audio_path).with_suffix(".concat.txt")
    concat_lines = [f"file '{Path(path).resolve().as_posix()}'" for path in audio_paths]
    concat_list_path.write_text("\n".join(concat_lines), encoding="utf-8")

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-c",
        "copy",
        output_audio_path,
    ]
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    finally:
        if concat_list_path.exists():
            concat_list_path.unlink()

    return output_audio_path


def create_slideshow_video(
    image_paths: list[str],
    durations: list[float],
    output_video_path: str,
    mouse_path: dict | None = None,
    timeout_seconds: int = 600,
) -> str:
    ensure_command_available("ffmpeg")
    if not image_paths:
        raise ValueError("No slide images were provided for slideshow rendering.")

    if len(image_paths) != len(durations):
        raise ValueError("Image path count and duration count must match.")

    output_path = Path(output_video_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame_dir = output_path.parent / f"{output_path.stem}_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    fps = SLIDESHOW_FPS
    slide_tracks = (mouse_path or {}).get("mouse_path", [])

    def interpolate_cursor(points: list[dict], time_value: float) -> tuple[float, float]:
        if not points:
            return (960.0, 360.0)
        if time_value <= points[0]["t"]:
            return float(points[0]["x"]), float(points[0]["y"])
        for current, nxt in zip(points, points[1:]):
            if current["t"] <= time_value <= nxt["t"]:
                span = max(nxt["t"] - current["t"], 1e-6)
                alpha = (time_value - current["t"]) / span
                x = current["x"] + (nxt["x"] - current["x"]) * alpha
                y = current["y"] + (nxt["y"] - current["y"]) * alpha
                return float(x), float(y)
        return float(points[-1]["x"]), float(points[-1]["y"])

    def draw_cursor(draw: ImageDraw.ImageDraw, x: float, y: float):
        halo_radius = 16
        draw.ellipse((x - halo_radius, y - halo_radius, x + halo_radius, y + halo_radius), outline="#F29E38", width=4)
        draw.polygon(
            [
                (x, y),
                (x + 18, y + 42),
                (x + 24, y + 28),
                (x + 38, y + 34),
                (x + 42, y + 24),
                (x + 28, y + 18),
                (x + 40, y + 8),
            ],
            fill="#FFFFFF",
            outline="#1F2933",
        )

    frame_index = 0
    for slide_index, (image_path, duration) in enumerate(zip(image_paths, durations)):
        base_image = Image.open(image_path).convert("RGB")
        width, height = base_image.size
        total_frames = max(int(round(max(duration, 1.0) * fps)), 1)
        track = slide_tracks[slide_index] if slide_index < len(slide_tracks) else {"points": []}

        for local_frame in range(total_frames):
            progress = local_frame / max(total_frames - 1, 1)
            zoom = 1.0 + 0.025 * progress
            focus_x, focus_y = interpolate_cursor(track.get("points", []), progress * max(duration, 1.0))
            crop_w = int(width / zoom)
            crop_h = int(height / zoom)
            center_x = int(width * 0.5 + (focus_x - width * 0.5) * 0.18)
            center_y = int(height * 0.5 + (focus_y - height * 0.5) * 0.18)
            left = min(max(center_x - crop_w // 2, 0), width - crop_w)
            top = min(max(center_y - crop_h // 2, 0), height - crop_h)
            frame = base_image.crop((left, top, left + crop_w, top + crop_h)).resize((width, height), Image.Resampling.LANCZOS)
            draw = ImageDraw.Draw(frame)
            draw_cursor(draw, focus_x, focus_y)
            frame.save(frame_dir / f"frame_{frame_index:06d}.png")
            frame_index += 1

    command = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(frame_dir / "frame_%06d.png"),
        "-pix_fmt",
        "yuv420p",
        "-vf",
        "fps=30,scale=1280:720",
        "-c:v",
        "libx264",
        output_video_path,
    ]

    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    finally:
        if frame_dir.exists():
            shutil.rmtree(frame_dir, ignore_errors=True)

    return output_video_path


def generate_english_audio(
    script_text: str,
    output_audio_path: str,
    timeout_seconds: int = 600,
    debug_output_dir: str | None = None,
):
    ensure_command_available("edge-tts")
    cleaned_text = normalize_voiceover_text(script_text)

    debug_dir_path = Path(debug_output_dir) if debug_output_dir else None
    if debug_dir_path is not None:
        debug_dir_path.mkdir(parents=True, exist_ok=True)
        (debug_dir_path / "last_voiceover.txt").write_text(script_text, encoding="utf-8")
        (debug_dir_path / "last_voiceover_cleaned.txt").write_text(cleaned_text, encoding="utf-8")

    chunk_text_paths: list[str] = []
    chunk_audio_paths: list[str] = []

    print("Generating TTS audio...")
    try:
        chunks = split_tts_text(cleaned_text)

        for index, chunk in enumerate(chunks, start=1):
            chunk_text_path = output_audio_path.replace(".mp3", f".part{index}.txt")
            chunk_audio_path = output_audio_path.replace(".mp3", f".part{index}.mp3")
            chunk_text_paths.append(chunk_text_path)
            chunk_audio_paths.append(chunk_audio_path)
            with open(chunk_text_path, "w", encoding="utf-8") as file:
                file.write(chunk)
            run_edge_tts(chunk_text_path, chunk_audio_path, timeout_seconds=min(timeout_seconds, 240))

        if len(chunk_audio_paths) == 1:
            os.replace(chunk_audio_paths[0], output_audio_path)
            chunk_audio_paths = []
        else:
            concat_audio_files(chunk_audio_paths, output_audio_path, timeout_seconds=timeout_seconds)

        print(f"Audio generated at: {output_audio_path}")
    except subprocess.CalledProcessError as exc:
        error_msg = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else "Unknown error"
        print(f"TTS error: {error_msg}")
        if debug_dir_path is not None:
            (debug_dir_path / "tts_error.txt").write_text(error_msg, encoding="utf-8")
        raise exc
    except subprocess.TimeoutExpired as exc:
        stdout_text = exc.stdout.decode("utf-8", errors="ignore") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr_text = exc.stderr.decode("utf-8", errors="ignore") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        error_msg = "\n".join(part for part in [stdout_text, stderr_text, "TTS timed out."] if part)
        print(f"TTS error: {error_msg}")
        if debug_dir_path is not None:
            (debug_dir_path / "tts_error.txt").write_text(error_msg, encoding="utf-8")
        raise exc
    finally:
        for path in [*chunk_text_paths, *chunk_audio_paths]:
            if os.path.exists(path):
                os.remove(path)

    return output_audio_path


def probe_media(media_path: str) -> dict:
    ensure_command_available("ffprobe")

    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        media_path,
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)

    duration_seconds = float(data.get("format", {}).get("duration", 0.0))
    video_stream = next((stream for stream in data["streams"] if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in data["streams"] if stream.get("codec_type") == "audio"), {})

    return {
        "duration_seconds": duration_seconds,
        "width": int(video_stream.get("width", 0) or 0),
        "height": int(video_stream.get("height", 0) or 0),
        "sample_rate": int(audio_stream.get("sample_rate", 0) or 0),
    }


def extend_video_to_duration(video_path: str, target_duration_seconds: float, timeout_seconds: int = 600) -> str:
    ensure_command_available("ffmpeg")

    current_duration = probe_media(video_path)["duration_seconds"]
    if current_duration >= target_duration_seconds:
        return video_path

    extension_seconds = max(target_duration_seconds - current_duration + 0.25, 0.25)
    input_path = Path(video_path)
    padded_path = input_path.with_name(f"{input_path.stem}_padded{input_path.suffix}")

    command = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-vf",
        f"tpad=stop_mode=clone:stop_duration={extension_seconds:.3f}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(padded_path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_seconds)
    return str(padded_path)


def merge_video_and_audio(video_path: str, audio_path: str, final_output_path: str, timeout_seconds: int = 600):
    ensure_command_available("ffmpeg")

    audio_duration = probe_media(audio_path)["duration_seconds"]
    usable_video_path = extend_video_to_duration(video_path, audio_duration, timeout_seconds=timeout_seconds)

    print("Merging video and audio with FFmpeg...")
    command = [
        "ffmpeg",
        "-y",
        "-i",
        usable_video_path,
        "-i",
        audio_path,
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-ar",
        str(MIN_AUDIO_SAMPLE_RATE),
        "-shortest",
        final_output_path,
    ]

    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
        print(f"Final merged video saved at: {final_output_path}")
    except subprocess.CalledProcessError as exc:
        error_msg = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else "Unknown error"
        print(f"FFmpeg error: {error_msg}")
        raise exc

    return final_output_path


def validate_final_media(video_path: str, audio_path: str):
    video_info = probe_media(video_path)
    audio_info = probe_media(audio_path)

    if video_info["height"] < MIN_VIDEO_HEIGHT:
        raise ValueError("Final video does not meet the minimum 720p requirement.")
    if audio_info["sample_rate"] < MIN_AUDIO_SAMPLE_RATE:
        raise ValueError("Audio sample rate is below the 16kHz requirement.")
    if video_info["duration_seconds"] > MAX_VIDEO_DURATION_SECONDS:
        raise ValueError("Final video exceeds the 30 minute limit.")
    if file_size_bytes(video_path) > MAX_VIDEO_SIZE_BYTES:
        raise ValueError("Final video exceeds the 3GB file size limit.")


def validate_supporting_files(subtitle_path: str | None, supplementary_paths: list[str]):
    if len(supplementary_paths) > MAX_SUPPLEMENTARY_FILES:
        raise ValueError("Supplementary file count exceeds the limit of 5.")

    relevant_paths = []
    if subtitle_path:
        relevant_paths.append(subtitle_path)
    relevant_paths.extend(supplementary_paths)

    if total_size_bytes(relevant_paths) > MAX_SUPPORTING_FILES_BYTES:
        raise ValueError("Subtitle and supplementary files exceed the 100MB combined limit.")


def format_vtt_timestamp(total_seconds: float) -> str:
    millis = int(round(total_seconds * 1000))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


def estimate_segments_to_total_duration(segments: list[str], total_duration: float) -> list[dict]:
    cleaned_segments = [segment.strip() for segment in segments if segment.strip()]
    if not cleaned_segments:
        return []

    word_counts = [max(len(segment.split()), 1) for segment in cleaned_segments]
    total_words = sum(word_counts)
    current_time = 0.0
    timed_segments = []

    for segment, word_count in zip(cleaned_segments, word_counts):
        duration = total_duration * (word_count / total_words)
        end_time = current_time + duration
        timed_segments.append(
            {
                "start": current_time,
                "end": end_time,
                "text": segment,
            }
        )
        current_time = end_time

    timed_segments[-1]["end"] = max(total_duration, timed_segments[-1]["end"])
    return timed_segments


def write_vtt_from_segments(segments: list[dict], output_subtitle_path: str):
    lines = ["WEBVTT", ""]

    for index, segment in enumerate(segments, start=1):
        lines.extend(
            [
                str(index),
                f"{format_vtt_timestamp(segment['start'])} --> {format_vtt_timestamp(segment['end'])}",
                segment["text"],
                "",
            ]
        )

    with open(output_subtitle_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines))

    return output_subtitle_path
