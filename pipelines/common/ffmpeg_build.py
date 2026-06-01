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


def _run(args: list[str]):
    log.debug("ffmpeg %s", " ".join(str(a) for a in args))
    try:
        p = subprocess.run([config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *map(str, args)],
                           capture_output=True, text=True)
    except FileNotFoundError:
        raise FFmpegMissing(f"FFmpeg binary '{config.FFMPEG}' not found on PATH "
                            "(install Gyan.FFmpeg)")
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{p.stderr[-2000:]}")


def probe_duration(path: Path) -> float:
    """Duration in seconds, or 0.0 if ffprobe is missing/unreadable (never raises)."""
    try:
        p = subprocess.run([config.FFPROBE, "-v", "error", "-show_entries",
                            "format=duration", "-of", "json", str(path)],
                           capture_output=True, text=True)
        return float(json.loads(p.stdout)["format"]["duration"])
    except FileNotFoundError:
        log.warning("ffprobe '%s' not found on PATH; treating duration as unknown", config.FFPROBE)
        return 0.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------- segments
def kenburns_segment(img: Path, dur: float, out: Path) -> Path:
    frames = max(1, int(dur * FPS))
    vf = (f"scale={int(W*1.5)}:{int(H*1.5)}:force_original_aspect_ratio=increase,"
          f"crop={int(W*1.5)}:{int(H*1.5)},"
          f"zoompan=z='min(zoom+0.0015,1.5)':d={frames}:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
          f"setsar=1,format=yuv420p")
    _run(["-loop", "1", "-framerate", FPS, "-t", f"{dur:.3f}", "-i", img,
          "-vf", vf, "-an", "-c:v", config.VIDEO_CODEC, "-pix_fmt", "yuv420p", out])
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
              "-c:v", config.VIDEO_CODEC, "-pix_fmt", "yuv420p", "-r", FPS, out])
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

    inputs = ["-i", video_track, "-i", vo_wav]
    if music:
        inputs += ["-stream_loop", "-1", "-i", music]

    sub = _ass_escape(ass)
    if music:
        filt = (
            f"[0:v]subtitles='{sub}'[v];"
            "[1:a]aresample=48000,aformat=channel_layouts=stereo,"
            "loudnorm=I=-16:TP=-1.5:LRA=11[vo];"
            "[2:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.35[mus];"
            "[mus][vo]sidechaincompress=threshold=0.04:ratio=10:attack=20:release=350[duck];"
            "[duck][vo]amix=inputs=2:duration=first:dropout_transition=0,"
            "alimiter=limit=0.95[aout]"
        )
    else:
        filt = (f"[0:v]subtitles='{sub}'[v];"
                "[1:a]aresample=48000,aformat=channel_layouts=stereo,"
                "loudnorm=I=-16:TP=-1.5:LRA=11[aout]")

    _run([*inputs, "-filter_complex", filt, "-map", "[v]", "-map", "[aout]",
          "-c:v", config.VIDEO_CODEC, "-pix_fmt", "yuv420p", "-c:a", config.AUDIO_CODEC,
          "-b:a", "192k", "-r", FPS, "-t", f"{total:.3f}", "-movflags", "+faststart", out_mp4])

    if thumb:
        _run(["-ss", f"{min(1.0, total/2):.2f}", "-i", out_mp4, "-vframes", "1",
              "-q:v", "3", thumb])
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
