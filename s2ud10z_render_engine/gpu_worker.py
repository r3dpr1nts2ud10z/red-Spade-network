import json
import os
import subprocess
from pathlib import Path


def dispatch_remote_render(job: dict, job_dir: Path, raw_video_path: Path) -> Path:
    """
    Dispatches a render job to a remote GPU worker (RunPod / Shadow) when configured.
    Supported environment variables:
      - GPU_SSH_HOST: e.g. "root@198.51.100.25"
      - GPU_SSH_PORT: optional SSH port (default: 22)
      - GPU_REMOTE_CMD: command template on GPU host; supports {job_id}, {title}, {out_path}
      - GPU_REMOTE_ARTIFACT: remote file path to scp back to raw_video_path
      - GPU_RENDER_URL: optional HTTP POST endpoint if using a GPU API worker instead of SSH
    """
    ssh_host = os.environ.get("GPU_SSH_HOST", "").strip()
    render_url = os.environ.get("GPU_RENDER_URL", "").strip()
    job_id = job.get("job_id", "rsn_job_001")
    title = job.get("title", job_id)

    job_dir.mkdir(parents=True, exist_ok=True)
    job_spec_file = job_dir / "remote_job_spec.json"
    job_spec_file.write_text(json.dumps(job, indent=2), encoding="utf-8")

    if ssh_host:
        port = os.environ.get("GPU_SSH_PORT", "22").strip() or "22"
        remote_cmd_template = os.environ.get(
            "GPU_REMOTE_CMD",
            "mkdir -p /tmp/rsn_out && ffmpeg -y -f lavfi -i color=c=0x18181b:s=1280x720:d=5 -pix_fmt yuv420p {out_path}",
        )
        remote_out = os.environ.get("GPU_REMOTE_ARTIFACT", f"/tmp/rsn_out/{job_id}_raw.mp4")
        remote_cmd = remote_cmd_template.format(
            job_id=job_id,
            title=title,
            out_path=remote_out,
        )

        ssh_base = ["ssh", "-p", port, "-o", "StrictHostKeyChecking=accept-new", ssh_host, remote_cmd]
        print(f"[GPU Worker] Dispatching via SSH to {ssh_host}:{port}...")
        subprocess.run(ssh_base, check=True)

        raw_video_path.parent.mkdir(parents=True, exist_ok=True)
        scp_cmd = [
            "scp",
            "-P",
            port,
            "-o",
            "StrictHostKeyChecking=accept-new",
            f"{ssh_host}:{remote_out}",
            str(raw_video_path),
        ]
        print(f"[GPU Worker] Pulling rendered artifact -> {raw_video_path}")
        subprocess.run(scp_cmd, check=True)
        return raw_video_path

    if render_url:
        import urllib.request

        payload = json.dumps({"job": job, "output_target": str(raw_video_path)}).encode("utf-8")
        req = urllib.request.Request(
            render_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        print(f"[GPU Worker] Posting job {job_id} to {render_url}...")
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read()
            if body:
                raw_video_path.parent.mkdir(parents=True, exist_ok=True)
                raw_video_path.write_bytes(body)
        return raw_video_path

    print("[GPU Worker] No GPU_SSH_HOST or GPU_RENDER_URL set; using local fallback generator.")
    raw_video_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x18181b:s=1280x720:d=5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(raw_video_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return raw_video_path
