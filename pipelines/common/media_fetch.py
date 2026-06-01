"""Acquire copyright-free footage/images from Archive.org, Pixabay, Pexels.

Every download records its source URL + license into the assets table. Files are
content-cached by URL hash so re-runs are idempotent. Only assets with a
confirmable free/CC/public-domain license are returned.
"""
from __future__ import annotations
import hashlib, logging
from pathlib import Path
import requests
from . import config, db

log = logging.getLogger("media")
TIMEOUT = 30
ASSETS = config.ASSETS


def _cache_path(url: str, suffix: str) -> Path:
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    return ASSETS / f"{h}{suffix}"


def _download(url: str, suffix: str) -> Path | None:
    dest = _cache_path(url, suffix)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    try:
        with requests.get(url, stream=True, timeout=TIMEOUT,
                          headers={"User-Agent": "reel-pipeline/1.0"}) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        return dest
    except Exception as e:
        log.warning("download failed %s (%s)", url, e)
        return None


# -------------------------------------------------------------- Pexels (video)
def pexels_videos(query: str, per_page: int = 5) -> list[dict]:
    if not config.PEXELS_API_KEY:
        return []
    try:
        r = requests.get("https://api.pexels.com/videos/search",
                         headers={"Authorization": config.PEXELS_API_KEY},
                         params={"query": query, "per_page": per_page,
                                 "orientation": "portrait"}, timeout=TIMEOUT)
        r.raise_for_status()
        out = []
        for v in r.json().get("videos", []):
            files = sorted(v["video_files"],
                           key=lambda f: (f.get("height") or 0), reverse=True)
            if files:
                out.append({"url": files[0]["link"], "source": "pexels",
                            "license": "Pexels License (free, no attribution req.)",
                            "page": v.get("url", ""), "kind": "footage"})
        return out
    except Exception as e:
        log.warning("pexels error %s", e); return []


# -------------------------------------------------------------- Pixabay (video/image)
def pixabay(query: str, kind: str = "video", per_page: int = 5) -> list[dict]:
    if not config.PIXABAY_API_KEY:
        return []
    base = "https://pixabay.com/api/videos/" if kind == "video" else "https://pixabay.com/api/"
    try:
        r = requests.get(base, params={"key": config.PIXABAY_API_KEY, "q": query,
                                       "per_page": per_page, "safesearch": "true"},
                         timeout=TIMEOUT)
        r.raise_for_status()
        out = []
        for hit in r.json().get("hits", []):
            if kind == "video":
                url = hit["videos"].get("large", {}).get("url") or hit["videos"]["medium"]["url"]
            else:
                url = hit.get("largeImageURL") or hit.get("webformatURL")
            out.append({"url": url, "source": "pixabay",
                        "license": "Pixabay Content License (free, no attribution req.)",
                        "page": hit.get("pageURL", ""), "kind": "footage" if kind == "video" else "image"})
        return out
    except Exception as e:
        log.warning("pixabay error %s", e); return []


# -------------------------------------------------------------- Archive.org (video)
def archive_videos(query: str, rows: int = 5) -> list[dict]:
    try:
        r = requests.get("https://archive.org/advancedsearch.php",
                         params={"q": f'({query}) AND mediatype:movies AND '
                                      'licenseurl:(*creativecommons* OR *publicdomain*)',
                                 "fl[]": "identifier", "rows": rows, "output": "json"},
                         timeout=TIMEOUT)
        r.raise_for_status()
        out = []
        for doc in r.json().get("response", {}).get("docs", []):
            ident = doc["identifier"]
            meta = requests.get(f"https://archive.org/metadata/{ident}", timeout=TIMEOUT).json()
            lic = meta.get("metadata", {}).get("licenseurl", "public domain / CC")
            for fobj in meta.get("files", []):
                name = fobj.get("name", "")
                if name.lower().endswith((".mp4", ".webm", ".ogv")):
                    out.append({"url": f"https://archive.org/download/{ident}/{name}",
                                "source": "archive.org", "license": lic,
                                "page": f"https://archive.org/details/{ident}",
                                "kind": "footage"})
                    break
        return out
    except Exception as e:
        log.warning("archive.org error %s", e); return []


def fetch_footage(keywords: list[str], draft_id: int, want: int) -> list[Path]:
    """Gather `want` footage clips across the three sources, logging licenses."""
    clips: list[Path] = []
    providers = []
    for kw in keywords:
        providers += pexels_videos(kw, 3) + pixabay(kw, "video", 3) + archive_videos(kw, 2)
    seen = set()
    for cand in providers:
        if len(clips) >= want:
            break
        if cand["url"] in seen:
            continue
        seen.add(cand["url"])
        p = _download(cand["url"], ".mp4")
        if p:
            db.log_asset(draft_id, cand["kind"], cand["source"], cand["page"],
                         cand["license"], p)
            clips.append(p)
    return clips


def fetch_images(keywords: list[str], draft_id: int, want: int) -> list[Path]:
    imgs: list[Path] = []
    cands = []
    for kw in keywords:
        cands += pixabay(kw, "image", 4)
    seen = set()
    for c in cands:
        if len(imgs) >= want:
            break
        if c["url"] in seen:
            continue
        seen.add(c["url"])
        p = _download(c["url"], ".jpg")
        if p:
            db.log_asset(draft_id, "image", c["source"], c["page"], c["license"], p)
            imgs.append(p)
    return imgs
