"""All video/audio processing via FFmpeg.

Pipeline A: Ken-Burns stills -> timed segments.
Pipeline B: stock footage -> scaled/cropped/trimmed portrait segments.
Both: concat segments, burn category-styled .ass subs, mix VO + ducked music,
export 1080x1920 H.264/AAC MP4. Also renders a thumbnail.
"""
from __future__ import annotations
import subprocess, logging, tempfile, json, os
from pathlib import Path
from . import config

log = logging.getLogger("ffmpeg")
W, H, FPS = config.WIDTH, config.HEIGHT, config.FPS


class FFmpegMissing(RuntimeError):
    """Raised when the ffmpeg/ffprobe binary is not on PATH."""


def _run(args: list[str], timeout: float | None = 600):
    log.debug("ffmpeg %s", " ".join(str(a) for a in args))
    try:
        p = subprocess.run([config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *map(str, args)],
                           capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise FFmpegMissing(f"FFmpeg binary '{config.FFMPEG}' not found on PATH "
                            "(install Gyan.FFmpeg)")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffmpeg timed out after {timeout}s (process killed); args: "
                           f"{' '.join(str(a) for a in args[:8])} ...")
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{p.stderr[-2000:]}")


def probe_duration(path: Path) -> float:
    """Duration in seconds, or 0.0 if ffprobe is missing/unreadable (never raises)."""
    try:
        p = subprocess.run([config.FFPROBE, "-v", "error", "-show_entries",
                            "format=duration", "-of", "json", str(path)],
                           capture_output=True, text=True, timeout=30)
        return float(json.loads(p.stdout)["format"]["duration"])
    except FileNotFoundError:
        log.warning("ffprobe '%s' not found on PATH; treating duration as unknown", config.FFPROBE)
        return 0.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------- segments
def kenburns_segment(img: Path, dur: float, out: Path) -> Path:
    """Render a still image to a video clip with a subtle Ken Burns zoom.

    zoompan expands a SINGLE input frame into ``frames`` output frames (the zoom
    accumulates across them), so the still is fed once and capped with
    ``-frames:v``. It must NOT be pre-looped into ``frames`` input frames: with
    ``-t``/looped input, zoompan emits ``d`` frames *per input frame* (frames**2),
    ballooning a ~5s clip to ~15min and showing only the first image after the
    export trim. A 1.5x supersample (== the max zoom) keeps the most zoomed-in
    frame pixel-sharp without the cost of a full 2x/4K pass.
    """
    frames = max(1, int(round(dur * FPS)))
    sw, sh = (W * 3) // 2, (H * 3) // 2  # 1.5x supersample, even dims for yuv420p
    vf = (
        f"scale={sw}:{sh}:force_original_aspect_ratio=increase,"
        f"crop={sw}:{sh},"
        f"zoompan=z='min(zoom+0.0015,1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={W}x{H}:fps={FPS},"
        "setsar=1,format=yuv420p"
    )
    _run(["-loop", "1", "-i", img, "-frames:v", frames,
          "-vf", vf, "-an", "-c:v", config.VIDEO_CODEC, "-preset", "veryfast",
          "-pix_fmt", "yuv420p", out])
    return out


def footage_segment(clip: Path, dur: float, out: Path) -> Path:
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},fps={FPS},setsar=1,format=yuv420p")
    _run(["-stream_loop", "-1", "-i", clip, "-t", f"{dur:.3f}",
          "-vf", vf, "-an", "-c:v", config.VIDEO_CODEC, "-pix_fmt", "yuv420p", out])
    return out


def _concat(segments: list[Path], out: Path) -> Path:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for s in segments:
            f.write(f"file '{Path(s).as_posix()}'\n")
        listfile = f.name
    try:
        _run(["-f", "concat", "-safe", "0", "-i", listfile,
              "-c:v", config.VIDEO_CODEC, "-preset", "veryfast",
              "-pix_fmt", "yuv420p", "-r", FPS, out])
    finally:
        os.unlink(listfile)
    return out


def _ass_escape(p: Path) -> str:
    # ffmpeg subtitles filter needs escaped backslashes and colon on Windows
    return str(p).replace("\\", "/").replace(":", "\\:")


# ---------------------------------------------------------------- final mux
def finalize(video_track: Path, vo_wav: Path, ass: Path, music: Path | None,
             out_mp4: Path, thumb: Path | None = None) -> Path:
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    total = probe_duration(video_track)
    if total <= 0.0:
        raise ValueError(
            f"finalize: cannot determine duration of {video_track}; "
            "ffprobe returned 0 (file may be corrupt or ffprobe missing)"
        )

    inputs = ["-i", video_track, "-i", vo_wav]
    if music:
        inputs += ["-stream_loop", "-1", "-i", music]

    sub = _ass_escape(ass)
    if music:
        filt = (
            f"[0:v]subtitles='{sub}'[v];"
            "[1:a]aresample=48000,aformat=channel_layouts=stereo,"
            "loudnorm=I=-16:TP=-1.5:LRA=11,asplit=2[vo_sc][vo_mix];"
            "[2:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.35[mus];"
            "[mus][vo_sc]sidechaincompress=threshold=0.04:ratio=10:attack=20:release=350[duck];"
            "[duck][vo_mix]amix=inputs=2:duration=first:dropout_transition=0,"
            "alimiter=limit=0.95[aout]"
        )
    else:
        filt = (f"[0:v]subtitles='{sub}'[v];"
                "[1:a]aresample=48000,aformat=channel_layouts=stereo,"
                "loudnorm=I=-16:TP=-1.5:LRA=11[aout]")

    _run([*inputs, "-filter_complex", filt, "-map", "[v]", "-map", "[aout]",
          "-c:v", config.VIDEO_CODEC, "-preset", "veryfast",
          "-pix_fmt", "yuv420p", "-c:a", config.AUDIO_CODEC,
          "-b:a", "192k", "-r", FPS, "-t", f"{total:.3f}", "-movflags", "+faststart", out_mp4])

    if thumb:
        _run(["-ss", f"{min(1.0, total/2):.2f}", "-i", out_mp4, "-vframes", "1",
              "-q:v", "3", thumb])
    return out_mp4


def enhance_audio(mp4: Path, cues: list[dict], sfx_paths: dict,
                  out_mp4: Path) -> Path:
    """Overlay timed SFX onto a finished reel and re-master the audio.

    `cues` = [{t: seconds, sfx: name, gain: linear}]; `sfx_paths` = {name: Path}.
    Video is stream-copied (no re-encode); audio is mixed with the SFX, then
    loudness-limited. Returns out_mp4. If there are no usable cues, the input is
    copied through unchanged so callers always get a valid file.
    """
    mp4, out_mp4 = Path(mp4), Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    usable = [c for c in cues if sfx_paths.get(c.get("sfx"))]
    if not usable:
        _run(["-i", mp4, "-c", "copy", out_mp4])
        return out_mp4

    inputs = ["-i", mp4]
    parts, labels = [], []
    for i, c in enumerate(usable, start=1):
        inputs += ["-i", str(sfx_paths[c["sfx"]])]
        delay_ms = int(max(0.0, float(c.get("t", 0))) * 1000)
        gain = float(c.get("gain", 0.5))
        parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms},volume={gain}[s{i}]")
        labels.append(f"[s{i}]")
    # original audio (label [0:a]) + all delayed SFX -> amix without auto-attenuation
    n = len(usable) + 1
    mix = (";".join(parts) + ";" +
           "[0:a]" + "".join(labels) +
           f"amix=inputs={n}:duration=first:normalize=0,"
           "alimiter=limit=0.95[aout]")
    _run([*inputs, "-filter_complex", mix,
          "-map", "0:v", "-map", "[aout]",
          "-c:v", "copy", "-c:a", config.AUDIO_CODEC, "-b:a", "192k",
          "-movflags", "+faststart", out_mp4])
    return out_mp4


def build_visual_from_images(images: list[Path], total_dur: float, workdir: Path) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    n = max(1, len(images))
    seg_dur = total_dur / n
    segs = []
    for i, img in enumerate(images):
        s = kenburns_segment(img, seg_dur, workdir / f"seg_{i:02d}.mp4")
        segs.append(s)
    return _concat(segs, workdir / "visual.mp4") if len(segs) > 1 else segs[0]


def build_visual_from_footage(clips: list[Path], total_dur: float, workdir: Path) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    n = max(1, len(clips))
    seg_dur = total_dur / n
    segs = []
    for i, clip in enumerate(clips):
        s = footage_segment(clip, seg_dur, workdir / f"seg_{i:02d}.mp4")
        segs.append(s)
    return _concat(segs, workdir / "visual.mp4") if len(segs) > 1 else segs[0]
