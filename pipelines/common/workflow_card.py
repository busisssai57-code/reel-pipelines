"""Per-reel reproducible 'workflow card' (takeaway #1: ship the assets).

Writes a sidecar JSON + Markdown next to each exported reel capturing everything
needed to reproduce or learn from it: script, beats/prompts, voice, mood, music,
visual source, render params, and every asset's source + license (from state.db).
Mirrors how pixaroma / Prompt Mastery / Youri publish exact workflows, not demos.
"""
from __future__ import annotations
import json, logging
from pathlib import Path
from . import config, db

log = logging.getLogger("workflow_card")


def _assets_for(draft_id: int) -> list[dict]:
    with db.conn() as c:
        rows = c.execute(
            "SELECT kind, source, url, license, local_path FROM assets WHERE draft_id=?",
            (draft_id,)).fetchall()
    return [dict(r) for r in rows]


def write_card(draft_id: int, pipeline: str, spec: dict, *, voice: str,
               visual_source: str, video_path: Path, render_params: dict | None = None) -> Path:
    """Write <video>.workflow.json and .md; return the markdown path."""
    video_path = Path(video_path)
    assets = _assets_for(draft_id)
    card = {
        "draft_id": draft_id,
        "pipeline": pipeline,
        "title": spec.get("title"),
        "topic": spec.get("topic") or spec.get("title"),
        "category": spec.get("category"),
        "mood": spec.get("mood"),
        "voice": voice,
        "visual_source": visual_source,
        "script": spec.get("full_script"),
        "beats": spec.get("beats", []),
        "keywords": spec.get("keywords", []),
        "render": render_params or {"width": config.WIDTH, "height": config.HEIGHT,
                                    "fps": config.FPS, "codec": config.VIDEO_CODEC},
        "assets": assets,
        "video": str(video_path),
    }
    json_path = video_path.with_suffix(".workflow.json")
    json_path.write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [f"# {card['title']}  ·  Pipeline {pipeline}",
          "",
          f"- **Category:** {card['category']}  ·  **Mood:** {card['mood']}",
          f"- **Voice:** {voice}  ·  **Visual source:** {visual_source}",
          f"- **Render:** {card['render'].get('width')}x{card['render'].get('height')} "
          f"@ {card['render'].get('fps')}fps ({card['render'].get('codec')})",
          "", "## Script", card.get("script") or "_(none)_", ""]
    if card["beats"]:
        md += ["## Beats / image prompts"]
        for i, b in enumerate(card["beats"], 1):
            md.append(f"{i}. {b.get('text','')}  —  _prompt:_ `{b.get('image_prompt','')}`")
        md.append("")
    if card["keywords"]:
        md += ["## Footage keywords", ", ".join(card["keywords"]), ""]
    md += ["## Assets & licenses (reproducibility)"]
    if assets:
        md += ["| kind | source | license | url |", "|---|---|---|---|"]
        for a in assets:
            md.append(f"| {a['kind']} | {a['source']} | {a['license']} | {a['url'] or ''} |")
    else:
        md.append("_No external assets logged (generated locally)._")
    md_path = video_path.with_suffix(".workflow.md")
    md_path.write_text("\n".join(md), encoding="utf-8")
    log.info("workflow card -> %s", md_path.name)
    return md_path
