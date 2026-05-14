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

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite")
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

    def repair_json_text(text: str) -> str:
        # Gemini sometimes returns LaTeX like \text or \frac inside JSON strings
        # without escaping the backslash for JSON. Preserve valid escapes and
        # double only the invalid ones.
        text = re.sub(r"\\(?![\"\\/bfnrtu])", r"\\\\", text)
        return text

    def extract_first_balanced_json_object(text: str) -> str | None:
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escaped = False

        for index in range(start, len(text)):
            char = text[index]

            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]

        return None

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        repaired = repair_json_text(cleaned)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        candidate = extract_first_balanced_json_object(cleaned)
        if not candidate:
            raise ValueError("LLM response did not contain a JSON object.")

        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return json.loads(repair_json_text(candidate))


def generate_text_with_gemini(prompt: str, max_attempts: int = 3) -> str:
    last_error = None
    models_to_try = [DEFAULT_MODEL]
    if FALLBACK_MODEL and FALLBACK_MODEL not in models_to_try:
        models_to_try.append(FALLBACK_MODEL)
    retryable_tokens = [
        "429",
        "503",
        "RESOURCE_EXHAUSTED",
        "UNAVAILABLE",
        "WINERROR 10053",
        "WINERROR 10054",
        "CONNECTIONRESETERROR",
        "CLIENTCONNECTORERROR",
        "READTIMEDOUT",
        "TIMED OUT",
    ]

    for model_name in models_to_try:
        for attempt in range(1, max_attempts + 1):
            try:
                response = client.models.generate_content(model=model_name, contents=prompt)
                return response.text.strip()
            except Exception as exc:
                last_error = exc
                error_text = f"{type(exc).__name__}: {exc}".upper()
                retryable = any(token in error_text for token in retryable_tokens)
                if not retryable:
                    raise RuntimeError(f"Gemini request failed: {exc}") from exc
                if attempt == max_attempts:
                    break
                sleep_seconds = min(15 * attempt, 45)
                print(
                    f"Gemini request failed for {model_name} on attempt {attempt}/{max_attempts}. "
                    f"Retrying in {sleep_seconds}s..."
                )
                time.sleep(sleep_seconds)

        if len(models_to_try) > 1 and model_name != models_to_try[-1]:
            print(f"Switching Gemini model from {model_name} to {models_to_try[-1]} after repeated failures.")

    raise RuntimeError(f"Gemini request failed after {max_attempts} attempts: {last_error}") from last_error


def generate_json_with_gemini(prompt: str, required_keys: list[str] | None = None) -> dict:
    last_error: Exception | None = None

    for attempt in range(1, 4):
        raw_text = generate_text_with_gemini(prompt)
        try:
            data = extract_json_object(raw_text)
            if required_keys:
                missing = [key for key in required_keys if key not in data]
                if missing:
                    raise ValueError(f"LLM response is missing required keys: {missing}")
            return data
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt == 3:
                break
            time.sleep(min(2 * attempt, 5))

    raise ValueError(f"Failed to parse strict JSON from Gemini after retries: {last_error}") from last_error


OUTLINE_REQUIRED_KEYS = [
    "course_title",
    "audience_summary",
    "teaching_goals",
    "prior_knowledge_assumptions",
    "forbidden_knowledge",
    "core_analogy",
    "factual_guardrails",
    "sections",
]


def validate_outline_data(data: dict) -> dict:
    missing = [key for key in OUTLINE_REQUIRED_KEYS if key not in data]
    if missing:
        raise ValueError(f"Outline is missing required keys: {missing}")
    return data


def validate_storyboard_data(data: dict) -> dict:
    if "slides" not in data:
        raise ValueError("Storyboard is missing required key: slides")
    slides = data.get("slides", [])
    if not isinstance(slides, list) or not slides:
        raise ValueError("Storyboard must contain a non-empty 'slides' list.")
    required_slide_keys = {
        "slide_id",
        "title",
        "teaching_purpose",
        "bridge_from_prior",
        "onscreen_text",
        "visual_plan",
        "narrative_hook",
        "analogy_or_example",
        "narration",
        "mini_recap",
        "formula",
        "estimated_seconds",
        "cursor_hint",
        "fact_check_notes",
        "source_note",
    }
    for slide in slides:
        missing = required_slide_keys.difference(slide.keys())
        if missing:
            raise ValueError(f"Storyboard slide is missing required keys: {sorted(missing)}")
    return data


def _split_sentences(text: str) -> list[str]:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [part.strip() for part in parts if part.strip()]


def _split_slide_for_pacing(slide: dict) -> tuple[dict, dict] | None:
    bullets = [str(item).strip() for item in slide.get("onscreen_text", []) if str(item).strip()]
    sentences = _split_sentences(slide.get("narration", ""))
    estimated = int(slide.get("estimated_seconds", 0) or 0)

    if len(bullets) < 2 and len(sentences) < 4 and estimated <= 22:
        return None

    bullet_mid = max(1, len(bullets) // 2)
    sentence_mid = max(1, len(sentences) // 2)

    first_bullets = bullets[:bullet_mid] or bullets[:1]
    second_bullets = bullets[bullet_mid:] or bullets[-1:]
    first_sentences = sentences[:sentence_mid] or sentences[:1]
    second_sentences = sentences[sentence_mid:] or sentences[-1:]

    first_slide = dict(slide)
    second_slide = dict(slide)

    first_slide["title"] = f"{slide.get('title', 'Slide')} (1)"
    second_slide["title"] = f"{slide.get('title', 'Slide')} (2)"
    first_slide["onscreen_text"] = first_bullets[:3]
    second_slide["onscreen_text"] = second_bullets[:3]
    first_slide["narration"] = " ".join(first_sentences).strip()
    second_slide["narration"] = " ".join(second_sentences).strip()
    first_slide["mini_recap"] = "Key setup before the next step."
    second_slide["bridge_from_prior"] = "Continue directly from the previous slide."
    second_slide["narrative_hook"] = "Now let's complete the idea."

    if first_slide.get("formula"):
        first_slide["formula"] = None

    first_seconds = max(8, estimated // 2) if estimated else max(8, len(first_slide["narration"].split()) // 3)
    second_seconds = max(8, estimated - first_seconds) if estimated else max(8, len(second_slide["narration"].split()) // 3)
    first_slide["estimated_seconds"] = min(first_seconds, 20)
    second_slide["estimated_seconds"] = min(max(second_seconds, 8), 20)

    return first_slide, second_slide


def normalize_storyboard_for_pacing(data: dict, min_slides: int = 7) -> dict:
    slides = [dict(slide) for slide in data.get("slides", [])]
    if not slides:
        return data

    changed = True
    while changed and len(slides) < min_slides:
        changed = False
        candidate_index = max(
            range(len(slides)),
            key=lambda i: (
                int(slides[i].get("estimated_seconds", 0) or 0),
                len(_split_sentences(slides[i].get("narration", ""))),
                len(slides[i].get("onscreen_text", [])),
            ),
        )
        split_pair = _split_slide_for_pacing(slides[candidate_index])
        if split_pair is None:
            break
        slides = slides[:candidate_index] + [split_pair[0], split_pair[1]] + slides[candidate_index + 1 :]
        changed = True

    for index, slide in enumerate(slides, start=1):
        slide["slide_id"] = f"slide{index}"
        slide["estimated_seconds"] = int(max(8, min(int(slide.get("estimated_seconds", 12) or 12), 20)))
        slide["onscreen_text"] = [str(item).strip() for item in slide.get("onscreen_text", []) if str(item).strip()][:3]
        slide["narration"] = " ".join(str(slide.get("narration", "")).split())
        slide["mini_recap"] = " ".join(str(slide.get("mini_recap", "")).split())

    return {"slides": slides}


def build_outline_prompt(course_requirement: str, student_persona: str) -> str:
    return f"""
You are an expert curriculum designer for the Teaching Monster competition.

Course requirement:
{course_requirement}

Student persona:
{student_persona}

Return exactly one JSON object with these keys:
- "course_title": short English title
- "audience_summary": concise summary of the learner
- "teaching_goals": list of 3 to 5 learning goals
- "prior_knowledge_assumptions": list of learner knowledge we can safely assume
- "forbidden_knowledge": list of ideas or formalisms that are too advanced unless carefully introduced
- "core_analogy": one high-quality analogy grounded in the learner's experience
- "factual_guardrails": list of factual or mathematical claims that must be handled carefully
- "sections": list of 3 to 6 section objects

Each section object must contain:
- "title"
- "goal"
- "bridge_from_previous": how this section connects from what the learner already knows
- "key_points": list of teaching points
- "why_it_matters_to_learner": short learner-centered motivation
- "visual_focus": how the visuals should support this section
- "misconception_to_fix": one likely misconception

Rules:
- English only
- Target secondary-school or intro college clarity
- Follow the requirement strictly
- Keep the plan lecture-friendly and suitable for a 30 minute max video
- Zero-hallucination mindset: do not invent theorems, citations, historical claims, datasets, or formulas
- Prefer simple, verified, canonical explanations over flashy but risky claims
- Build the lesson from known ideas toward new ideas with explicit scaffolding

Return JSON only.
"""


def build_storyboard_prompt(outline: dict, course_requirement: str, student_persona: str) -> str:
    return f"""
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
- "teaching_purpose": what conceptual job this slide performs
- "bridge_from_prior": how this slide starts from what the learner already understands
- "onscreen_text": list of short bullet-sized strings
- "visual_plan": detailed description of what should appear on screen
- "narrative_hook": one attention-maintaining move such as curiosity, contrast, or a motivating question
- "analogy_or_example": one learner-appropriate analogy, concrete example, or intuition anchor
- "narration": spoken script for this slide
- "mini_recap": one or two sentences summarizing what the learner should now understand
- "formula": LaTeX string or null
- "estimated_seconds": integer estimate for this slide narration duration
- "cursor_hint": what area of the slide the audience should focus on
- "fact_check_notes": list of short notes describing which claims must stay precise
- "source_note": either "original explanation" or a short attribution note if an external fact is explicitly referenced

Rules:
- 7 to 10 slides total
- English only
- Narration should be engaging but concise
- On-screen text must stay short and readable
- Limit `onscreen_text` to 2 to 4 bullets, each usually under 7 words
- `visual_plan` should describe concrete objects and motion cues, not a long paragraph
- Prefer visual explanation over text density
- Prefer one micro-idea per slide instead of packing many ideas into one slide
- Typical `estimated_seconds` should be about 8 to 18 seconds per slide
- If a concept needs more time, split it across consecutive slides rather than making one long slide
- Every slide must clearly connect to the student persona and avoid abrupt jumps in difficulty
- Use staged teaching: intuition first, then structure, then formalization, then recap
- Student-facing content must never show internal instructional-design language such as "bridge from prior", "teaching purpose", "this slide does", or meta commentary for content developers
- Do not fabricate citations, named studies, or specific statistics unless truly necessary and widely canonical
- The last slide must contain a clean summary and one transfer idea for the learner

Return JSON only.
"""


def generate_course_outline(course_requirement: str, student_persona: str) -> dict:
    data = generate_json_with_gemini(build_outline_prompt(course_requirement, student_persona))
    return validate_outline_data(data)


def generate_storyboard(outline: dict, course_requirement: str, student_persona: str) -> dict:
    data = generate_json_with_gemini(build_storyboard_prompt(outline, course_requirement, student_persona))
    return normalize_storyboard_for_pacing(validate_storyboard_data(data))


def generate_outline_and_storyboard(course_requirement: str, student_persona: str) -> tuple[dict, dict]:
    prompt = f"""
You are designing a complete text-to-video teaching lesson in one shot.

Requirement:
{course_requirement}

Student persona:
{student_persona}

Return exactly one JSON object with these keys:
- "outline": an outline object
- "storyboard": a storyboard object

The "outline" object must follow this schema:
{build_outline_prompt(course_requirement, student_persona)}

The "storyboard" object must follow this schema and must be consistent with the outline:
{build_storyboard_prompt({"note": "Use the generated outline from this same response."}, course_requirement, student_persona)}

Global rules:
- The storyboard must be derived from the outline in the same response
- English only
- JSON only
- No markdown fences
- No explanations before or after the JSON
"""
    data = generate_json_with_gemini(prompt, required_keys=["outline", "storyboard"])
    outline = validate_outline_data(data["outline"])
    storyboard = normalize_storyboard_for_pacing(validate_storyboard_data(data["storyboard"]))
    return outline, storyboard


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
- Reflect the pedagogical structure in the storyboard: hook, scaffold, example, recap
- Build visuals from shapes, text, arrows, tables, coordinate planes, braces, highlights, and LaTeX
- Avoid external images, internet assets, or local file dependencies
- Never use `ImageMobject`, `SVGMobject`, `TexturedSurface`, `Sphere`, `ThreeDScene`, or any filename like `assets/...`, `.png`, `.jpg`, `.jpeg`, `.svg`
- Use only self-contained 2D primitives that exist in standard Manim Community
- Keep text readable at 720p
- Use separate visual beats for each slide/section
- Make the visuals synchronize with the narration emphasis: when the narration introduces a contrast, comparison, misconception, or formula, the animation should highlight that exact element at the same moment
- Use the slide `cursor_hint`, `narrative_hook`, `analogy_or_example`, and `mini_recap` fields as guidance for pacing and emphasis
- Use waits and pacing so the animation is long enough for the target duration
- Only use Manim functions and rate functions that are known to exist in standard `from manim import *`
- Prefer `linear`, `smooth`, `there_and_back`, or omit `rate_func` entirely
- Use `Group` instead of `VGroup` when collecting arbitrary `self.mobjects`
- Do not include unsupported claims, fake citations, or decorative visuals that do not help comprehension
- End with a short final pause
"""


def generate_manim_lesson(storyboard: dict, target_duration_seconds: int, repair_context: str | None = None) -> dict:
    code = generate_text_with_gemini(
        build_manim_prompt(storyboard, target_duration_seconds, repair_context=repair_context)
    )
    cleaned = code.replace("```python", "").replace("```", "").strip()
    start_index = cleaned.find("from manim import *")
    if start_index != -1:
        cleaned = cleaned[start_index:].strip()
    if not cleaned.startswith("from manim import *"):
        raise ValueError("Generated Manim code did not start with `from manim import *`.")
    return {"manim_code": cleaned}


def sanitize_manim_code(manim_code: str) -> str:
    allowed_rate_funcs = {"linear", "smooth", "there_and_back", "double_smooth", "slow_into"}

    def replace_rate_func(match: re.Match) -> str:
        candidate = match.group(1)
        if candidate in allowed_rate_funcs:
            return f"rate_func={candidate}"
        return "rate_func=smooth"

    sanitized = re.sub(
        r"rate_func\s*=\s*([A-Za-z_][A-Za-z0-9_]*)(?:\.[A-Za-z_][A-Za-z0-9_]*)*",
        replace_rate_func,
        manim_code,
    )
    sanitized = re.sub(r"rate_func\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s+t\s*:\s*[^,\)\n]+", r"rate_func=\1", sanitized)
    sanitized = re.sub(r"rate_func\s*=\s*lambda\s+t\s*:\s*[^,\)\n]+", "rate_func=smooth", sanitized)
    sanitized = re.sub(r"rate_func\s*=\s*[^,\)\n]*\bt\s*:\s*[^,\)\n]+", "rate_func=smooth", sanitized)
    sanitized = re.sub(r"\)\s*\*\*\s*\d+", ")", sanitized)
    sanitized = sanitized.replace("rush_from", "smooth")
    sanitized = sanitized.replace("rush_into", "smooth")
    sanitized = sanitized.replace("BROWN_D", "BROWN")
    sanitized = sanitized.replace("align_direction=", "aligned_edge=")
    sanitized = sanitized.replace("VGroup(*self.mobjects)", "Group(*self.mobjects)")
    sanitized = sanitized.replace("FadeOut(VGroup(*self.mobjects))", "FadeOut(Group(*self.mobjects))")
    sanitized = re.sub(
        r"ImageMobject\([^\n]+\)",
        'RoundedRectangle(width=1.8, height=1.2, corner_radius=0.15, color=BLUE_D, fill_opacity=0.15)',
        sanitized,
    )
    sanitized = re.sub(
        r"SVGMobject\([^\n]+\)",
        'RoundedRectangle(width=1.8, height=0.9, corner_radius=0.2, color=BLUE_D, fill_opacity=0.15)',
        sanitized,
    )
    sanitized = re.sub(
        r"Speedometer\(\)",
        "Circle(radius=0.35, color=GREEN, fill_opacity=0)",
        sanitized,
    )
    sanitized = re.sub(r"[A-Za-z_][A-Za-z0-9_]*\.get_vector\(\)", "RIGHT", sanitized)
    sanitized = sanitized.replace("Sphere(", "Circle(")
    sanitized = sanitized.replace(".set_z(", ".set_z_index(")
    sanitized = re.sub(
        r"\.set_shading_config\(\{.*?\}\)",
        "",
        sanitized,
        flags=re.DOTALL,
    )
    return sanitized


def render_manim_code(
    manim_code: str,
    output_path: str,
    timeout_seconds: int = 1200,
    debug_output_dir: str | None = None,
) -> str:
    if shutil.which("manim") is None:
        raise RuntimeError("The 'manim' command is not available in the current environment.")

    OUTPUT_ROOT.mkdir(exist_ok=True)
    output_path_obj = Path(output_path)
    base_filename = output_path_obj.stem
    script_path = Path(f"temp_{base_filename}.py")

    sanitized_code = sanitize_manim_code(manim_code)
    with script_path.open("w", encoding="utf-8") as file:
        file.write(sanitized_code)

    debug_dir_path = Path(debug_output_dir) if debug_output_dir else None
    if debug_dir_path is not None:
        debug_dir_path.mkdir(parents=True, exist_ok=True)
        (debug_dir_path / "last_manim_code.py").write_text(sanitized_code, encoding="utf-8")

    try:
        compile(sanitized_code, str(script_path), "exec")
    except SyntaxError as exc:
        syntax_report = f"{exc.__class__.__name__}: {exc}\n"
        if debug_dir_path is not None:
            (debug_dir_path / "manim_render_error.txt").write_text(syntax_report, encoding="utf-8")
        raise ManimRenderError("Sanitized Manim code is still invalid Python.", syntax_report) from exc

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
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.CalledProcessError as exc:
        render_log = "\n".join(part for part in [exc.stdout, exc.stderr] if part).strip()
        print(f"Manim rendering failed. Check the generated script: {script_path}")
        if debug_dir_path is not None:
            (debug_dir_path / "manim_render_error.txt").write_text(render_log, encoding="utf-8")
        raise ManimRenderError("Manim rendering failed.", render_log) from exc
    except subprocess.TimeoutExpired as exc:
        render_log = "\n".join(
            part for part in [exc.stdout or "", exc.stderr or "", "Render timed out."] if part
        ).strip()
        print(f"Manim rendering timed out. Check the generated script: {script_path}")
        if debug_dir_path is not None:
            (debug_dir_path / "manim_render_error.txt").write_text(render_log, encoding="utf-8")
        raise ManimRenderError("Manim rendering timed out.", render_log) from exc
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
