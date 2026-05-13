from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.staticfiles import StaticFiles

from pipeline import TeachingVideoPipeline

OUTPUT_ROOT = Path("outputs")
OUTPUT_ROOT.mkdir(exist_ok=True)

app = FastAPI(title="Teaching Monster API", version="1.0.0")
app.mount("/outputs", StaticFiles(directory=OUTPUT_ROOT), name="outputs")

pipeline = TeachingVideoPipeline(output_root=str(OUTPUT_ROOT))


class TeachingRequest(BaseModel):
    request_id: str = Field(..., description="Unique request ID for caching and output paths.")
    course_requirement: str
    student_persona: str


class TeachingResponse(BaseModel):
    video_url: str
    subtitle_url: str
    supplementary_url: list[str]


def build_public_url(request: Request, file_path: Path) -> str:
    relative_path = file_path.relative_to(OUTPUT_ROOT).as_posix()
    return f"{str(request.base_url).rstrip('/')}/outputs/{relative_path}"


@app.get("/health")
@app.get("/v1/health")
def health_check():
    return {
        "status": "ok",
        "service": "teaching-monster-api",
    }


@app.post("/generate", response_model=TeachingResponse)
@app.post("/v1/video/generate", response_model=TeachingResponse)
def generate_educational_video(payload: TeachingRequest, request: Request):
    print(f"--- Starting Task: {payload.request_id} ---")

    if request.headers.get("X-Dry-Run", "").lower() == "true":
        return TeachingResponse(
            video_url="https://example.com/test.mp4",
            subtitle_url="https://example.com/test.vtt",
            supplementary_url=[],
        )

    try:
        result = pipeline.run(
            request_id=payload.request_id,
            course_requirement=payload.course_requirement,
            student_persona=payload.student_persona,
        )

        return TeachingResponse(
            video_url=build_public_url(request, Path(result["final_video_path"])),
            subtitle_url=build_public_url(request, Path(result["subtitle_path"])),
            supplementary_url=[
                build_public_url(request, Path(result["outline_path"])),
                build_public_url(request, Path(result["storyboard_path"])),
                build_public_url(request, Path(result["manim_bundle_path"])),
            ],
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        print(f"Pipeline validation failed: {exc}")
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        print(f"Error during video generation: {exc}")
        raise HTTPException(status_code=500, detail="Failed to generate video.") from exc


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
