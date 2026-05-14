# Teaching Monster Competition Server

This project exposes a synchronous HTTP API for the Teaching Monster competition. The server waits until the video and subtitle files are fully generated before returning URLs, matching the competition requirement that downloads start immediately after the API response.

The current rendering pipeline uses an HTML/CSS slide deck route instead of LLM-generated Manim code:

- `outline + storyboard` generation with Gemini
- slide deck export to `slides.md` and `slides.html`
- deterministic slide image rendering with Pillow
- slideshow video rendering with FFmpeg
- narration generation with `edge-tts`
- final MP4 merge plus VTT subtitles

## API

- `POST /v1/video/generate`
- `POST /generate`
- `GET /v1/health`
- `GET /health`

### Request JSON

```json
{
  "request_id": "demo_request_001",
  "course_requirement": "Explain Newton's second law to a 10th grader in English.",
  "student_persona": "I am a 10th grade student with basic algebra knowledge and no calculus background."
}
```

### Response JSON

```json
{
  "video_url": "https://your-host/outputs/demo_request_001/final.mp4",
  "subtitle_url": "https://your-host/outputs/demo_request_001/subtitles.vtt",
  "supplementary_url": []
}
```

## Competition Compliance Notes

- JSON over HTTP/HTTPS: Supported.
- Full automation: The pipeline is end-to-end automated from prompt intake to MP4/VTT output.
- Response timing: The server returns only after media files are generated and validated.
- Video format: MP4 output.
- Resolution check: Enforced at runtime, minimum 720p.
- Audio sample rate check: Enforced at runtime, minimum 16 kHz.
- Video length check: Enforced at runtime, maximum 30 minutes.
- Video file size check: Enforced at runtime, maximum 3 GB.
- Subtitle plus supplementary size check: Enforced at runtime, maximum 100 MB combined.
- Supplementary file count: Enforced at runtime, maximum 5 files.
- Link retention: Request outputs are marked with `available_until_utc` and configured to remain available for at least 72 hours by default.
- External media sources: This pipeline does not fetch third-party images, charts, or datasets. Visuals are generated from internal slide templates and LLM-authored text. As a result, no third-party asset attribution is required for the current implementation.
- External services used:
  - Gemini API via `google-genai`
  - Microsoft Edge TTS via `edge-tts`

## Environment Variables

- `GEMINI_API_KEY`: Required.
- `GEMINI_MODEL`: Optional, default `gemini-2.5-flash`.
- `GEMINI_FALLBACK_MODEL`: Optional, default `gemini-2.5-flash-lite`.
- `MAX_REQUEST_RUNTIME_SECONDS`: Optional, default `1740` seconds (29 minutes).
- `OUTPUT_RETENTION_HOURS`: Optional, default `72`.

## Local Run

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the API:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Docker

Build:

```bash
docker build -t teaching-monster-api .
```

Run:

```bash
docker run --rm -p 8000:8000 -e GEMINI_API_KEY=your_key -v $(pwd)/outputs:/app/outputs teaching-monster-api
```

Use a persistent volume for `/app/outputs` so download links remain valid for the retention window.

### GCP VM Example

If you deploy on a VM and map host port `80` to container port `8000`, use:

```bash
docker run -d \
  --name ai-api \
  --restart always \
  -p 80:8000 \
  -e GEMINI_API_KEY="your_key" \
  -e PUBLIC_BASE_URL="http://YOUR_GCP_EXTERNAL_IP" \
  -v $(pwd)/outputs:/app/outputs \
  teaching-monster-api
```

Then test:

```bash
curl http://YOUR_GCP_EXTERNAL_IP/v1/health
```

Your competition endpoint would be:

```text
http://YOUR_GCP_EXTERNAL_IP/v1/video/generate
```

## Output Retention

Each request writes metadata to `outputs/<request_id>/intermediates/request.json`, including `available_until_utc`.

To delete expired requests after the retention window:

```bash
python cleanup_outputs.py
```

## Operational Assumptions

- The server process must stay online and the `outputs` directory must remain mounted on persistent storage to satisfy the 48-hour link validity requirement in practice.
- The Gemini API key must have sufficient quota for live requests.
- The container or host must be reachable from the competition evaluator over HTTP/HTTPS.
