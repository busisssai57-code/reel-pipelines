"""Local image generation for Pipeline A.

Preference order (all free/open):
  1) diffusers Stable Diffusion locally (if torch + diffusers installed),
  2) copyright-free stock images from Pixabay (logged with license),
  3) a generated gradient placeholder via FFmpeg so the pipeline still renders.
"""
from __future__ import annotations
import logging, hashlib
from pathlib import Path
from . import config, media_fetch, ffmpeg_build

log = logging.getLogger("imagegen")
_pipe = None
_PALETTE = ["0x1b2a4a", "0x3a2a1b", "0x1b3a2a", "0x3a1b2a", "0x2a1b3a", "0x1b3a3a"]


def _sd():
    global _pipe
    if _pipe is None:
        import torch
        from diffusers import StableDiffusionPipeline
        _pipe = StableDiffusionPipeline.from_pretrained(
            "runwayml/stable-diffusion-v1-5",
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32)
        _pipe = _pipe.to("cuda" if torch.cuda.is_available() else "cpu")
    return _pipe


def _placeholder(prompt: str, out: Path) -> Path:
    color = _PALETTE[int(hashlib.sha1(prompt.encode()).hexdigest(), 16) % len(_PALETTE)]
    ffmpeg_build._run([
        "-f", "lavfi", "-i",
        f"gradients=s={config.WIDTH}x{config.HEIGHT}:c0={color}:c1=0x000000:duration=1",
        "-frames:v", "1", out])
    return out


def generate_images(prompts: list[str], outdir: Path, draft_id: int) -> list[Path]:
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []

    # 1) local Stable Diffusion
    try:
        pipe = _sd()
        for i, p in enumerate(prompts):
            img = pipe(p + ", vertical 9:16, cinematic, high detail",
                       height=768, width=448).images[0]
            dest = outdir / f"img_{i:02d}.png"
            img.save(dest)
            out.append(dest)
        if out:
            log.info("generated %d images via Stable Diffusion", len(out))
            return out
    except Exception as e:
        log.warning("SD unavailable (%s); trying stock images", e)

    # 2) Pixabay stock
    stock = media_fetch.fetch_images(prompts, draft_id, want=len(prompts))
    if stock:
        log.info("using %d stock images", len(stock))
        # top up with placeholders if short
        for i in range(len(stock), len(prompts)):
            stock.append(_placeholder(prompts[i], outdir / f"ph_{i:02d}.png"))
        return stock

    # 3) placeholders
    log.warning("no image source available; generating placeholders")
    for i, p in enumerate(prompts):
        out.append(_placeholder(p, outdir / f"ph_{i:02d}.png"))
    return out
