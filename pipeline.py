import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from manim_engine import generate_course_outline, generate_outline_and_storyboard, generate_storyboard
from media_utils import (
    create_slideshow_video,
    estimate_segments_to_total_duration,
    generate_english_audio,
    merge_video_and_audio,
    probe_media,
    validate_final_media,
    validate_supporting_files,
    write_vtt_from_segments,
)
from slide_renderer import (
    build_marp_markdown,
    build_mouse_paths,
    build_page_scripts,
    build_slide_html,
    build_slides_prompt,
    render_storyboard_to_images,
)

MAX_REQUEST_RUNTIME_SECONDS = int(os.getenv("MAX_REQUEST_RUNTIME_SECONDS", "1740"))
OUTPUT_RETENTION_HOURS = int(os.getenv("OUTPUT_RETENTION_HOURS", "72"))


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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TeachingVideoPipeline:
    def __init__(self, output_root: str = "outputs"):
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)

    def ensure_within_runtime_limit(self, start_time: float, stage_name: str):
        elapsed = time.monotonic() - start_time
        if elapsed > MAX_REQUEST_RUNTIME_SECONDS:
            raise TimeoutError(f"Pipeline exceeded the time limit during '{stage_name}'.")

    def build_request_metadata(self, safe_request_id: str, course_requirement: str, student_persona: str) -> dict:
        available_until = datetime.now(timezone.utc) + timedelta(hours=OUTPUT_RETENTION_HOURS)
        return {
            "request_id": safe_request_id,
            "course_requirement": course_requirement,
            "student_persona": student_persona,
            "created_at_utc": utc_now_iso(),
            "available_until_utc": available_until.isoformat(),
            "retention_hours": OUTPUT_RETENTION_HOURS,
            "generation_policy": {
                "full_automation": True,
                "external_media_sources_used": False,
                "source_attribution_required": "No external third-party assets are fetched by this pipeline.",
                "llm_service": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                "tts_service": "edge-tts",
            },
        }

    def run(self, request_id: str, course_requirement: str, student_persona: str) -> dict:
        start_time = time.monotonic()
        safe_request_id = sanitize_request_id(request_id)
        request_dir = self.output_root / safe_request_id
        request_dir.mkdir(parents=True, exist_ok=True)

        intermediates_dir = request_dir / "intermediates"
        request_meta_path = intermediates_dir / "request.json"
        outline_path = intermediates_dir / "outline.json"
        storyboard_path = intermediates_dir / "storyboard.json"
        slides_prompt_path = intermediates_dir / "slides_prompt.json"
        page_scripts_path = intermediates_dir / "page_scripts.json"
        mouse_path_path = intermediates_dir / "mouse_path.json"
        render_bundle_path = intermediates_dir / "render_bundle.json"
        slides_markdown_path = request_dir / "slides.md"
        slides_html_path = request_dir / "slides.html"
        slide_images_dir = request_dir / "slide_images"

        raw_video_path = request_dir / "raw.mp4"
        audio_path = request_dir / "voiceover.mp3"
        final_video_path = request_dir / "final.mp4"
        subtitle_path = request_dir / "subtitles.vtt"

        supplementary_paths = [
            str(slides_markdown_path),
            str(slides_html_path),
            str(slides_prompt_path),
            str(page_scripts_path),
            str(mouse_path_path),
        ]

        save_json(
            self.build_request_metadata(safe_request_id, course_requirement, student_persona),
            request_meta_path,
        )

        if final_video_path.exists() and subtitle_path.exists():
            validate_final_media(str(final_video_path), str(audio_path))
            validate_supporting_files(str(subtitle_path), supplementary_paths)
            return {
                "request_id": safe_request_id,
                "request_dir": str(request_dir),
                "final_video_path": str(final_video_path),
                "subtitle_path": str(subtitle_path),
                "supplementary_paths": supplementary_paths,
                "outline_path": str(outline_path),
                "storyboard_path": str(storyboard_path),
                "slides_prompt_path": str(slides_prompt_path),
                "page_scripts_path": str(page_scripts_path),
                "mouse_path_path": str(mouse_path_path),
                "render_bundle_path": str(render_bundle_path),
                "request_meta_path": str(request_meta_path),
            }

        self.ensure_within_runtime_limit(start_time, "startup")
        outline = None
        storyboard = None

        if outline_path.exists():
            outline = load_json(outline_path)
        if storyboard_path.exists():
            storyboard = load_json(storyboard_path)

        if outline is None and storyboard is None:
            outline, storyboard = generate_outline_and_storyboard(course_requirement, student_persona)
            save_json(outline, outline_path)
            save_json(storyboard, storyboard_path)
        else:
            if outline is None:
                outline = generate_course_outline(course_requirement, student_persona)
                save_json(outline, outline_path)

            self.ensure_within_runtime_limit(start_time, "outline generation")
            if storyboard is None:
                storyboard = generate_storyboard(outline, course_requirement, student_persona)
                save_json(storyboard, storyboard_path)

        narration_segments = [slide["narration"].strip() for slide in storyboard["slides"]]
        voiceover_text = "\n\n".join(narration_segments)
        estimated_segment_durations = [
            int(slide.get("estimated_seconds", 0) or 0) for slide in storyboard["slides"]
        ]
        target_duration_seconds = max(sum(max(value, 6) for value in estimated_segment_durations), 20)
        slide_durations = [max(float(value or 0), 4.0) for value in estimated_segment_durations]

        self.ensure_within_runtime_limit(start_time, "storyboard generation")
        save_json(build_slides_prompt(storyboard), slides_prompt_path)
        save_json(build_page_scripts(storyboard), page_scripts_path)
        mouse_path_data = build_mouse_paths(storyboard, slide_durations)
        save_json(mouse_path_data, mouse_path_path)

        if not slides_markdown_path.exists():
            slides_markdown_path.write_text(build_marp_markdown(outline, storyboard), encoding="utf-8")
        if not slides_html_path.exists():
            slides_html_path.write_text(build_slide_html(outline, storyboard), encoding="utf-8")

        self.ensure_within_runtime_limit(start_time, "tts generation")
        if not audio_path.exists():
            remaining_budget = max(60, int(MAX_REQUEST_RUNTIME_SECONDS - (time.monotonic() - start_time)))
            generate_english_audio(
                voiceover_text,
                str(audio_path),
                timeout_seconds=min(remaining_budget, 600),
                debug_output_dir=str(intermediates_dir),
            )

        self.ensure_within_runtime_limit(start_time, "slide rendering")
        slide_image_paths = render_storyboard_to_images(storyboard, str(slide_images_dir))
        render_bundle = {
            "render_mode": "html_css_slides",
            "slide_image_paths": slide_image_paths,
            "slide_durations": slide_durations,
            "slides_markdown_path": str(slides_markdown_path),
            "slides_html_path": str(slides_html_path),
            "slides_prompt_path": str(slides_prompt_path),
            "page_scripts_path": str(page_scripts_path),
            "mouse_path_path": str(mouse_path_path),
        }
        save_json(render_bundle, render_bundle_path)

        self.ensure_within_runtime_limit(start_time, "slideshow video rendering")
        remaining_budget = max(120, int(MAX_REQUEST_RUNTIME_SECONDS - (time.monotonic() - start_time)))
        create_slideshow_video(
            slide_image_paths,
            slide_durations,
            str(raw_video_path),
            mouse_path=mouse_path_data,
            timeout_seconds=min(remaining_budget, 600),
        )

        self.ensure_within_runtime_limit(start_time, "audio-video merge")
        remaining_budget = max(120, int(MAX_REQUEST_RUNTIME_SECONDS - (time.monotonic() - start_time)))
        merge_video_and_audio(
            str(raw_video_path),
            str(audio_path),
            str(final_video_path),
            timeout_seconds=min(remaining_budget, 600),
        )

        final_duration = probe_media(str(final_video_path))["duration_seconds"]
        subtitle_segments = estimate_segments_to_total_duration(narration_segments, final_duration)
        write_vtt_from_segments(subtitle_segments, str(subtitle_path))
        validate_final_media(str(final_video_path), str(audio_path))
        validate_supporting_files(str(subtitle_path), supplementary_paths)

        self.ensure_within_runtime_limit(start_time, "final validation")
        return {
            "request_id": safe_request_id,
            "request_dir": str(request_dir),
            "final_video_path": str(final_video_path),
            "subtitle_path": str(subtitle_path),
            "supplementary_paths": supplementary_paths,
            "outline_path": str(outline_path),
            "storyboard_path": str(storyboard_path),
            "slides_prompt_path": str(slides_prompt_path),
            "page_scripts_path": str(page_scripts_path),
            "mouse_path_path": str(mouse_path_path),
            "render_bundle_path": str(render_bundle_path),
            "request_meta_path": str(request_meta_path),
        }
