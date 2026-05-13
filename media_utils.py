import json
import os
import shutil
import subprocess
from pathlib import Path


def ensure_command_available(command_name: str):
    if shutil.which(command_name) is None:
        raise RuntimeError(f"The '{command_name}' command is not available in the current environment.")


def generate_english_audio(script_text: str, output_audio_path: str):
    ensure_command_available("edge-tts")

    temp_text_path = output_audio_path.replace(".mp3", ".txt")
    with open(temp_text_path, "w", encoding="utf-8") as file:
        file.write(script_text)

    print("Generating TTS audio...")
    command = [
        "edge-tts",
        "--voice",
        "en-US-ChristopherNeural",
        "-f",
        temp_text_path,
        "--write-media",
        output_audio_path,
    ]

    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"Audio generated at: {output_audio_path}")
    except subprocess.CalledProcessError as exc:
        error_msg = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else "Unknown error"
        print(f"TTS error: {error_msg}")
        raise exc
    finally:
        if os.path.exists(temp_text_path):
            os.remove(temp_text_path)

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


def extend_video_to_duration(video_path: str, target_duration_seconds: float) -> str:
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
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return str(padded_path)


def merge_video_and_audio(video_path: str, audio_path: str, final_output_path: str):
    ensure_command_available("ffmpeg")

    audio_duration = probe_media(audio_path)["duration_seconds"]
    usable_video_path = extend_video_to_duration(video_path, audio_duration)

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
        "16000",
        "-shortest",
        final_output_path,
    ]

    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"Final merged video saved at: {final_output_path}")
    except subprocess.CalledProcessError as exc:
        error_msg = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else "Unknown error"
        print(f"FFmpeg error: {error_msg}")
        raise exc

    return final_output_path


def validate_final_media(video_path: str, audio_path: str):
    video_info = probe_media(video_path)
    audio_info = probe_media(audio_path)

    if video_info["height"] < 720:
        raise ValueError("Final video does not meet the minimum 720p requirement.")
    if audio_info["sample_rate"] < 16000:
        raise ValueError("Audio sample rate is below the 16kHz requirement.")
    if video_info["duration_seconds"] > 30 * 60:
        raise ValueError("Final video exceeds the 30 minute limit.")


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
