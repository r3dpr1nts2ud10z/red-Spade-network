import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def run_cmd(cmd: list[str], step_name: str) -> None:
    print(f"[{step_name}] Running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"[{step_name}] Failed (code {proc.returncode}):\n{proc.stderr}")
    print(f"[{step_name}] Completed.")


def stage_blender(job: dict, work_dir: Path, dry_run: bool = False) -> Path:
    b_cfg = job["blender"]
    raw_dir = work_dir / "blender_pass"
    raw_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        print("[Blender] Dry-run mode: generating synthetic 3D proxy pass via FFmpeg...")
        proxy_mp4 = raw_dir / "proxy_stage.mp4"
        run_cmd(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"testsrc2=size={b_cfg['width']}x{b_cfg['height']}:rate={b_cfg['fps']}:duration=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(proxy_mp4),
            ],
            "Blender Dry-Run Proxy",
        )
        return raw_dir

    env = os.environ.copy()
    env["S2UD10Z_OUT_DIR"] = str(raw_dir)
    env["S2UD10Z_FPS"] = str(b_cfg["fps"])
    env["S2UD10Z_W"] = str(b_cfg["width"])
    env["S2UD10Z_H"] = str(b_cfg["height"])

    cmd = ["blender", "--background", b_cfg["blend_file"], "--python", b_cfg["scene_script"]]
    run_cmd(cmd, "Blender Headless Stage")
    return raw_dir


def queue_comfy_prompt(comfy_url: str, workflow: dict) -> str:
    payload = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(
        f"{comfy_url.rstrip('/')}/prompt",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["prompt_id"]


def wait_for_comfy(comfy_url: str, prompt_id: str, poll_sec: float = 2.0) -> dict:
    history_url = f"{comfy_url.rstrip('/')}/history/{prompt_id}"
    while True:
        with urllib.request.urlopen(history_url, timeout=30) as resp:
            history = json.loads(resp.read().decode("utf-8"))
        if prompt_id in history:
            return history[prompt_id]
        time.sleep(poll_sec)


def stage_comfyui(job: dict, blender_dir: Path, work_dir: Path, dry_run: bool = False) -> Path:
    gen_dir = work_dir / "comfy_pass"
    gen_dir.mkdir(parents=True, exist_ok=True)
    rendered_mp4 = gen_dir / "comfy_out.mp4"

    if dry_run:
        print("[ComfyUI] Dry-run mode: bypassing GPU API and forwarding proxy pass...")
        proxy_mp4 = blender_dir / "proxy_stage.mp4"
        run_cmd(["cp", str(proxy_mp4), str(rendered_mp4)], "ComfyUI Dry-Run Pass")
        return rendered_mp4

    c_cfg = job["comfyui"]
    with open(c_cfg["workflow_json"], "r", encoding="utf-8") as f:
        workflow = json.load(f)

    for node in workflow.values():
        meta_title = node.get("_meta", {}).get("title", "")
        inputs = node.get("inputs", {})
        if meta_title == "S2UD10Z_BLENDER_DIR" and "directory" in inputs:
            inputs["directory"] = str(blender_dir)
        elif meta_title == "S2UD10Z_AUDIO_VO" and "audio" in inputs:
            inputs["audio"] = job["audio"]["voiceover_wav"]
        elif meta_title == "S2UD10Z_STYLE_PROMPT" and "text" in inputs:
            inputs["text"] = c_cfg["prompt_style"]
        elif meta_title == "S2UD10Z_DENOISE" and "denoise" in inputs:
            inputs["denoise"] = c_cfg["denoise"]

    prompt_id = queue_comfy_prompt(c_cfg["url"], workflow)
    print(f"[ComfyUI] Queued prompt_id={prompt_id}, waiting for render...")
    wait_for_comfy(c_cfg["url"], prompt_id)

    if not rendered_mp4.exists():
        run_cmd(
            [
                "ffmpeg", "-y",
                "-framerate", str(job["blender"]["fps"]),
                "-i", str(gen_dir / "frame_%05d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(rendered_mp4),
            ],
            "ComfyUI Frame Stitch",
        )
    return rendered_mp4


def stage_ffmpeg_broadcast(job: dict, video_in: Path, dry_run: bool = False) -> tuple[Path, Path]:
    out_dir = Path(job["output"]["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    mp4_out = out_dir / job["output"]["mp4_master"]
    hls_out = out_dir / job["output"]["hls_playlist"]
    vo_path = job["audio"]["voiceover_wav"]
    bed_path = job["audio"].get("music_bed")
    target_lufs = job["audio"].get("target_lufs", -14.0)

    if dry_run and not os.path.exists(vo_path):
        run_cmd(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", vo_path],
            "Generate Test VO Audio",
        )

    if bed_path and os.path.exists(bed_path):
        filter_complex = (
            f"[1:a]volume=1.0[vo];"
            f"[2:a]volume=0.22[bed];"
            f"[vo][bed]amix=inputs=2:duration=shortest[mixed];"
            f"[mixed]loudnorm=I={target_lufs}:TP=-1.5:LRA=11[aout]"
        )
        audio_map = ["-map", "0:v:0", "-map", "[aout]", "-filter_complex", filter_complex]
    else:
        audio_map = ["-map", "0:v:0", "-map", "1:a:0", "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"]

    run_cmd(
        [
            "ffmpeg", "-y",
            "-i", str(video_in),
            "-i", vo_path,
            *(["-i", bed_path] if bed_path and os.path.exists(bed_path) else []),
            *audio_map,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            str(mp4_out),
        ],
        "FFmpeg Master MP4",
    )

    run_cmd(
        [
            "ffmpeg", "-y",
            "-i", str(mp4_out),
            "-c", "copy",
            "-hls_time", "4",
            "-hls_playlist_type", "vod",
            "-hls_segment_filename", str(out_dir / "seg_%03d.ts"),
            str(hls_out),
        ],
        "FFmpeg HLS Package",
    )

    return mp4_out, hls_out


def run_job(manifest_path: str, dry_run: bool = False) -> None:
    with open(manifest_path, "r", encoding="utf-8") as f:
        job = json.load(f)

    work_dir = Path("/tmp/s2ud10z_work") / job["job_id"]
    work_dir.mkdir(parents=True, exist_ok=True)

    blender_dir = stage_blender(job, work_dir, dry_run=dry_run)
    comfy_video = stage_comfyui(job, blender_dir, work_dir, dry_run=dry_run)
    mp4_master, hls_playlist = stage_ffmpeg_broadcast(job, comfy_video, dry_run=dry_run)

    print("\n=== S2UD10Z RENDER COMPLETE ===")
    print(f"Job ID   : {job['job_id']}")
    print(f"Channel  : {job['channel_id']}")
    print(f"MP4      : {mp4_master}")
    print(f"HLS Feed : {hls_playlist}")
    from publish_manifest import write_job_manifest
    from build_lineup import build_channel_feed
    feed_item = write_job_manifest(job, mp4_master, hls_playlist)
    lineup_file = Path(__file__).resolve().parent / "out" / "channel_feed.json"
    build_channel_feed(Path(__file__).resolve().parent, lineup_file)
    print(f"Feed Item: {feed_item}")
    print(f"Lineup   : {lineup_file}")



if __name__ == "__main__":
    manifest = sys.argv[1] if len(sys.argv) > 1 else "render_job.json"
    is_dry_run = "--dry-run" in sys.argv
    run_job(manifest, dry_run=is_dry_run)
