import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def write_job_manifest(job: dict, mp4_path: Path, hls_path: Path) -> Path:
    out_dir = Path(job["output"]["out_dir"])
    base_url = job.get("publish", {}).get(
        "base_url",
        f"https://r3dpr1nts2ud10z.github.io/red-Spade-network/render_engine/{out_dir.as_posix()}",
    ).rstrip("/")

    ts_files = sorted(p.name for p in out_dir.glob("seg_*.ts"))
    payload = {
        "job_id": job["job_id"],
        "channel_id": job["channel_id"],
        "title": job["title"],
        "framing": job.get("framing", "educational_parody"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "streams": {
            "hls": f"{base_url}/{hls_path.name}",
            "mp4": f"{base_url}/{mp4_path.name}",
        },
        "files": {
            "playlist": hls_path.name,
            "master": mp4_path.name,
            "segments": ts_files,
        },
    }

    manifest_out = out_dir / "feed_item.json"
    with open(manifest_out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return manifest_out


if __name__ == "__main__":
    job_file = Path(sys.argv[1] if len(sys.argv) > 1 else "render_job.json")
    with open(job_file, "r", encoding="utf-8") as f:
        job_data = json.load(f)
    out_dir = Path(job_data["output"]["out_dir"])
    mp4 = out_dir / job_data["output"]["mp4_master"]
    hls = out_dir / job_data["output"]["hls_playlist"]
    written = write_job_manifest(job_data, mp4, hls)
    print(f"Wrote feed item: {written}")
