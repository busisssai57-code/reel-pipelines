"""Local image generation for Pipeline A.

Preference order (all free/open):
  1) diffusers Stable Diffusion locally (if torch + diffusers installed),
  2) copyright-free stock images from Pixabay (logged with license),
  3) locally generated procedural key art so the pipeline still renders.
"""
from __future__ import annotations
import logging, hashlib, math, textwrap
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
    """Create premium local key art when no external/source model is available."""
    try:
        return _procedural_key_art(prompt, out)
    except Exception as e:
        log.warning("procedural key art failed (%s); using ffmpeg gradient", e)
    color = _PALETTE[int(hashlib.sha1(prompt.encode()).hexdigest(), 16) % len(_PALETTE)]
    ffmpeg_build._run([
        "-f", "lavfi", "-i",
        f"gradients=s={config.WIDTH}x{config.HEIGHT}:c0={color}:c1=0x000000:duration=1",
        "-frames:v", "1", out])
    return out


def _procedural_key_art(prompt: str, out: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(prompt.encode("utf-8")).digest()
    c0 = _rgb(_PALETTE[digest[0] % len(_PALETTE)])
    c1 = (8, 12, 24)
    accent = (64 + digest[1] % 160, 120 + digest[2] % 110, 180 + digest[3] % 70)

    img = Image.new("RGB", (config.WIDTH, config.HEIGHT), c1)
    px = img.load()
    for y in range(config.HEIGHT):
        t = y / max(1, config.HEIGHT - 1)
        wave = 0.08 * math.sin((y / 120) + digest[4])
        for x in range(config.WIDTH):
            radial = ((x - config.WIDTH * 0.55) ** 2 + (y - config.HEIGHT * 0.42) ** 2) ** 0.5
            glow = max(0, 1 - radial / (config.HEIGHT * 0.72))
            mix = min(1, max(0, t + wave - glow * 0.35))
            px[x, y] = tuple(int(c0[i] * (1 - mix) + c1[i] * mix + accent[i] * glow * 0.35)
                             for i in range(3))

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for i in range(18):
        x = int((digest[i % len(digest)] / 255) * config.WIDTH)
        y = int(((digest[(i + 5) % len(digest)] / 255) * config.HEIGHT))
        r = 16 + digest[(i + 9) % len(digest)] % 48
        d.ellipse((x - r, y - r, x + r, y + r), outline=(*accent, 70), width=3)
    for y in range(180, config.HEIGHT, 220):
        d.line((80, y, config.WIDTH - 80, y - 90), fill=(*accent, 55), width=5)

    panel = Image.new("RGBA", (config.WIDTH - 120, 560), (4, 8, 18, 178))
    panel = panel.filter(ImageFilter.GaussianBlur(0.5))
    overlay.alpha_composite(panel, (60, int(config.HEIGHT * 0.56)))

    img = Image.alpha_composite(img.convert("RGBA"), overlay)
    d = ImageDraw.Draw(img)
    title = _title_from_prompt(prompt)
    font_big = _font(ImageFont, 96)
    font_mid = _font(ImageFont, 48)
    font_small = _font(ImageFont, 36)

    d.text((82, 120), "LOCAL AI STUDIO", fill=(220, 245, 255, 210), font=font_small)
    d.rounded_rectangle((82, 170, 455, 228), radius=26, outline=(*accent, 210), width=4)
    d.text((112, 181), "HIGH RETENTION VISUAL", fill=(255, 255, 255, 235), font=font_small)

    y = int(config.HEIGHT * 0.60)
    for line in textwrap.wrap(title.upper(), width=15)[:4]:
        d.text((92, y), line, fill=(255, 255, 255, 255), font=font_big,
               stroke_width=4, stroke_fill=(0, 0, 0, 210))
        y += 104
    d.text((96, y + 20), "Procedural key art generated fully offline",
           fill=(220, 245, 255, 225), font=font_mid)

    img.convert("RGB").save(out, quality=94)
    return out


def _title_from_prompt(prompt: str) -> str:
    clean = " ".join(prompt.replace(",", " ").replace(":", " ").split())
    words = [w for w in clean.split() if len(w) > 2]
    return " ".join(words[:8]) or "Cinematic Story Beat"


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.replace("0x", "").replace("#", "")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _font(image_font, size: int):
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return image_font.truetype(name, size)
        except Exception:
            pass
    return image_font.load_default()


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

    # 3) local procedural key art
    log.warning("no image source available; generating local procedural key art")
    for i, p in enumerate(prompts):
        out.append(_placeholder(p, outdir / f"ph_{i:02d}.png"))
    return out
