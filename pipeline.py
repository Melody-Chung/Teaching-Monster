import json
import re
from pathlib import Path

from manim_engine import (
    ManimRenderError,
    generate_course_outline,
    generate_manim_lesson,
    generate_storyboard,
    render_manim_code,
)
from media_utils import (
    estimate_segments_to_total_duration,
    generate_english_audio,
    merge_video_and_audio,
    probe_media,
    validate_final_media,
    write_vtt_from_segments,
)


def sanitize_request_id(request_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", request_id).strip("._")
    return safe or "request"


def save_json(data: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


class TeachingVideoPipeline:
    def __init__(self, output_root: str = "outputs", max_manim_retries: int = 2):
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.max_manim_retries = max_manim_retries

    def run(self, request_id: str, course_requirement: str, student_persona: str) -> dict:
        safe_request_id = sanitize_request_id(request_id)
        request_dir = self.output_root / safe_request_id
        request_dir.mkdir(parents=True, exist_ok=True)

        intermediates_dir = request_dir / "intermediates"
        request_meta_path = intermediates_dir / "request.json"
        outline_path = intermediates_dir / "outline.json"
        storyboard_path = intermediates_dir / "storyboard.json"
        manim_bundle_path = intermediates_dir / "manim_bundle.json"

        raw_video_path = request_dir / "raw.mp4"
        audio_path = request_dir / "voiceover.mp3"
        final_video_path = request_dir / "final.mp4"
        subtitle_path = request_dir / "subtitles.vtt"

        save_json(
            {
                "request_id": safe_request_id,
                "course_requirement": course_requirement,
                "student_persona": student_persona,
            },
            request_meta_path,
        )

        if final_video_path.exists() and subtitle_path.exists():
            return {
                "request_id": safe_request_id,
                "request_dir": str(request_dir),
                "final_video_path": str(final_video_path),
                "subtitle_path": str(subtitle_path),
                "outline_path": str(outline_path),
                "storyboard_path": str(storyboard_path),
                "manim_bundle_path": str(manim_bundle_path),
            }

        if outline_path.exists():
            outline = load_json(outline_path)
        else:
            outline = generate_course_outline(course_requirement, student_persona)
            save_json(outline, outline_path)

        if storyboard_path.exists():
            storyboard = load_json(storyboard_path)
        else:
            storyboard = generate_storyboard(outline, course_requirement, student_persona)
            save_json(storyboard, storyboard_path)

        narration_segments = [slide["narration"].strip() for slide in storyboard["slides"]]
        voiceover_text = "\n\n".join(narration_segments)
        estimated_segment_durations = [
            int(slide.get("estimated_seconds", 0) or 0) for slide in storyboard["slides"]
        ]
        target_duration_seconds = max(sum(max(value, 6) for value in estimated_segment_durations), 20)

        if manim_bundle_path.exists():
            manim_bundle = load_json(manim_bundle_path)
        else:
            manim_bundle = generate_manim_lesson(storyboard, target_duration_seconds)
            save_json(manim_bundle, manim_bundle_path)

        if not audio_path.exists():
            generate_english_audio(voiceover_text, str(audio_path))

        actual_raw_video_path = None
        latest_bundle = manim_bundle
        repair_context = None

        for attempt in range(1, self.max_manim_retries + 2):
            try:
                actual_raw_video_path = render_manim_code(latest_bundle["manim_code"], str(raw_video_path))
                save_json(latest_bundle, manim_bundle_path)
                break
            except ManimRenderError as exc:
                if attempt > self.max_manim_retries:
                    raise
                repair_context = (
                    f"Attempt {attempt} failed.\n"
                    f"Render error:\n{exc.render_log[-6000:]}\n"
                    "Please produce a corrected complete Manim script."
                )
                latest_bundle = generate_manim_lesson(
                    storyboard,
                    target_duration_seconds,
                    repair_context=repair_context,
                )

        if actual_raw_video_path is None:
            raise RuntimeError("Failed to render Manim video after retries.")

        merge_video_and_audio(actual_raw_video_path, str(audio_path), str(final_video_path))

        final_duration = probe_media(str(final_video_path))["duration_seconds"]
        subtitle_segments = estimate_segments_to_total_duration(narration_segments, final_duration)
        write_vtt_from_segments(subtitle_segments, str(subtitle_path))
        validate_final_media(str(final_video_path), str(audio_path))

        return {
            "request_id": safe_request_id,
            "request_dir": str(request_dir),
            "final_video_path": str(final_video_path),
            "subtitle_path": str(subtitle_path),
            "outline_path": str(outline_path),
            "storyboard_path": str(storyboard_path),
            "manim_bundle_path": str(manim_bundle_path),
        }
