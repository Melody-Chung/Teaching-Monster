import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY not found. Please check your .env file.")

client = genai.Client(api_key=api_key)

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
OUTPUT_ROOT = Path("outputs")


@dataclass
class ManimRenderError(RuntimeError):
    message: str
    render_log: str

    def __str__(self) -> str:
        return self.message


def extract_json_object(raw_text: str) -> dict:
    cleaned = raw_text.strip()
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError("LLM response did not contain a JSON object.")
        return json.loads(match.group(0))


def generate_text_with_gemini(prompt: str, max_attempts: int = 3) -> str:
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(model=DEFAULT_MODEL, contents=prompt)
            return response.text.strip()
        except Exception as exc:
            last_error = exc
            error_text = str(exc)
            retryable = any(token in error_text for token in ["429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE"])
            if not retryable:
                raise RuntimeError(f"Gemini request failed: {exc}") from exc
            if attempt == max_attempts:
                break
            sleep_seconds = min(15 * attempt, 45)
            print(f"Gemini request failed on attempt {attempt}/{max_attempts}. Retrying in {sleep_seconds}s...")
            time.sleep(sleep_seconds)

    raise RuntimeError(f"Gemini request failed after {max_attempts} attempts: {last_error}") from last_error


def generate_json_with_gemini(prompt: str, required_keys: list[str] | None = None) -> dict:
    data = extract_json_object(generate_text_with_gemini(prompt))

    if required_keys:
        missing = [key for key in required_keys if key not in data]
        if missing:
            raise ValueError(f"LLM response is missing required keys: {missing}")

    return data


def generate_course_outline(course_requirement: str, student_persona: str) -> dict:
    prompt = f"""
You are an expert curriculum designer for the Teaching Monster competition.

Course requirement:
{course_requirement}

Student persona:
{student_persona}

Return exactly one JSON object with these keys:
- "course_title": short English title
- "audience_summary": concise summary of the learner
- "teaching_goals": list of 3 to 5 learning goals
- "sections": list of 3 to 6 section objects

Each section object must contain:
- "title"
- "goal"
- "key_points": list of teaching points
- "visual_focus": how the visuals should support this section
- "misconception_to_fix": one likely misconception

Rules:
- English only
- Target secondary-school or intro college clarity
- Follow the requirement strictly
- Keep the plan lecture-friendly and suitable for a 30 minute max video

Return JSON only.
"""
    return generate_json_with_gemini(
        prompt,
        required_keys=["course_title", "audience_summary", "teaching_goals", "sections"],
    )


def generate_storyboard(outline: dict, course_requirement: str, student_persona: str) -> dict:
    prompt = f"""
You are building a text-to-video lesson pipeline.

Requirement:
{course_requirement}

Student persona:
{student_persona}

Course outline JSON:
{json.dumps(outline, ensure_ascii=False, indent=2)}

Return exactly one JSON object with these keys:
- "slides": a list of slide objects

Each slide object must contain:
- "slide_id": "slide1", "slide2", ...
- "title": short title
- "onscreen_text": list of short bullet-sized strings
- "visual_plan": detailed description of what should appear on screen
- "narration": spoken script for this slide
- "formula": LaTeX string or null
- "estimated_seconds": integer estimate for this slide narration duration
- "cursor_hint": what area of the slide the audience should focus on

Rules:
- 4 to 8 slides total
- English only
- Narration should be engaging but concise
- On-screen text must stay short and readable
- Visual plan should fit a 3Blue1Brown / teaching animation style

Return JSON only.
"""
    data = generate_json_with_gemini(prompt, required_keys=["slides"])
    slides = data.get("slides", [])
    if not isinstance(slides, list) or not slides:
        raise ValueError("Storyboard must contain a non-empty 'slides' list.")
    return data


def build_manim_prompt(storyboard: dict, target_duration_seconds: int, repair_context: str | None = None) -> str:
    repair_block = ""
    if repair_context:
        repair_block = f"""
Previous render failed. Fix the code using this error report:
{repair_context}

Return a corrected full script, not an explanation.
"""

    return f"""
You are an English STEM teacher and a Manim v0.19.1 animator.

Storyboard JSON:
{json.dumps(storyboard, ensure_ascii=False, indent=2)}

Target total duration: about {target_duration_seconds} seconds.
{repair_block}
Return only full Python code. No JSON. No markdown fences.

Rules for the code:
- Must start with `from manim import *`
- Must define exactly one class `GeneratedScene(Scene)`
- Use the storyboard slide order faithfully
- Build visuals from shapes, text, arrows, tables, coordinate planes, braces, highlights, and LaTeX
- Avoid external images, internet assets, or local file dependencies
- Keep text readable at 720p
- Use separate visual beats for each slide/section
- Use waits and pacing so the animation is long enough for the target duration
- Only use Manim functions and rate functions that are known to exist in standard `from manim import *`
- Prefer `linear`, `smooth`, `there_and_back`, or omit `rate_func` entirely
- Use `Group` instead of `VGroup` when collecting arbitrary `self.mobjects`
- End with a short final pause
"""


def generate_manim_lesson(storyboard: dict, target_duration_seconds: int, repair_context: str | None = None) -> dict:
    code = generate_text_with_gemini(
        build_manim_prompt(storyboard, target_duration_seconds, repair_context=repair_context)
    )
    cleaned = code.replace("```python", "").replace("```", "").strip()
    if not cleaned.startswith("from manim import *"):
        raise ValueError("Generated Manim code did not start with `from manim import *`.")
    return {"manim_code": cleaned}


def sanitize_manim_code(manim_code: str) -> str:
    allowed_rate_funcs = {"linear", "smooth", "there_and_back", "double_smooth", "slow_into"}

    def replace_rate_func(match: re.Match) -> str:
        candidate = match.group(1)
        if candidate in allowed_rate_funcs:
            return match.group(0)
        return "rate_func=smooth"

    sanitized = re.sub(r"rate_func\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", replace_rate_func, manim_code)
    sanitized = sanitized.replace("rush_from", "smooth")
    sanitized = sanitized.replace("rush_into", "smooth")
    sanitized = sanitized.replace("VGroup(*self.mobjects)", "Group(*self.mobjects)")
    sanitized = sanitized.replace("FadeOut(VGroup(*self.mobjects))", "FadeOut(Group(*self.mobjects))")
    return sanitized


def render_manim_code(manim_code: str, output_path: str) -> str:
    if shutil.which("manim") is None:
        raise RuntimeError("The 'manim' command is not available in the current environment.")

    OUTPUT_ROOT.mkdir(exist_ok=True)
    output_path_obj = Path(output_path)
    base_filename = output_path_obj.stem
    script_path = Path(f"temp_{base_filename}.py")

    with script_path.open("w", encoding="utf-8") as file:
        file.write(sanitize_manim_code(manim_code))

    command = [
        "manim",
        str(script_path),
        "GeneratedScene",
        "-qm",
        "--media_dir",
        str(OUTPUT_ROOT),
        "-o",
        base_filename,
    ]

    print(f"Starting Manim render for: {base_filename}")
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        render_log = "\n".join(part for part in [exc.stdout, exc.stderr] if part).strip()
        print(f"Manim rendering failed. Check the generated script: {script_path}")
        raise ManimRenderError("Manim rendering failed.", render_log) from exc
    finally:
        if script_path.exists():
            script_path.unlink()

    actual_video_path = (
        OUTPUT_ROOT / "videos" / f"temp_{base_filename}" / "720p30" / f"{base_filename}.mp4"
    ).resolve()

    if not actual_video_path.exists():
        raise FileNotFoundError(f"Video not found at {actual_video_path}")

    if result.stderr.strip():
        print(result.stderr.strip())

    return str(actual_video_path)
