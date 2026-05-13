import json
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_ROOT = Path("outputs")


def parse_timestamp(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)


def main():
    now = datetime.now(timezone.utc)
    removed = []

    for request_dir in OUTPUT_ROOT.iterdir() if OUTPUT_ROOT.exists() else []:
        if not request_dir.is_dir():
            continue

        meta_path = request_dir / "intermediates" / "request.json"
        if not meta_path.exists():
            continue

        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            expires_at = parse_timestamp(metadata["available_until_utc"])
        except Exception:
            continue

        if expires_at <= now:
            for child in sorted(request_dir.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    try:
                        child.rmdir()
                    except OSError:
                        pass
            try:
                request_dir.rmdir()
            except OSError:
                pass
            removed.append(request_dir.name)

    print({"removed_requests": removed, "count": len(removed)})


if __name__ == "__main__":
    main()
