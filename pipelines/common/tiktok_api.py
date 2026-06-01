"""TikTok API integration: upload video, fetch metrics."""
from __future__ import annotations
import logging, urllib.request, json, time
from . import config, db

log = logging.getLogger("tiktok_api")

def get_access_token() -> str | None:
    """Get or refresh TikTok access token from db."""
    token_data = db.get_platform_token("tiktok")
    if not token_data:
        log.warning("No TikTok token stored; run setup-oauth.ps1 tiktok")
        return None

    # Check if token expired; refresh if needed
    if token_data.get("expires_at", 0) < time.time():
        if not _refresh_token(token_data["refresh_token"]):
            return None
        token_data = db.get_platform_token("tiktok")

    return token_data.get("access_token")

def _refresh_token(refresh_token: str) -> bool:
    """Refresh TikTok token using OAuth2 endpoint."""
    try:
        url = "https://open.tiktokapis.com/v2/oauth/token/"
        data = {
            "client_key": config.TIKTOK_CLIENT_KEY,
            "client_secret": config.TIKTOK_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("data", {}).get("access_token"):
                db.set_platform_token(
                    "tiktok",
                    result["data"]["access_token"],
                    refresh_token,  # usually doesn't change
                    time.time() + result["data"].get("expires_in", 14400),
                    "video.upload,video.publish",
                )
                return True
    except Exception as e:
        log.error(f"TikTok token refresh failed: {e}")
    return False

def upload_video(draft: dict) -> str | None:
    """
    Upload video to TikTok via Content Posting API v2.
    Returns tiktok_video_id or None.
    """
    access_token = get_access_token()
    if not access_token:
        return None

    video_path = draft.get("video_path")
    if not video_path:
        return None

    try:
        # Step 1: Initialize upload
        init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
        init_body = {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": int(Path(video_path).stat().st_size),
            },
            "post_info": {
                "title": draft.get("title", f"Reel {draft.get('id')}"),
                "description": draft.get("script", "")[:300],  # TikTok limit
                "privacy_level": "PUBLIC_TO_ANYONE",
                "disable_comment": False,
                "disable_duet": False,
                "disable_stitch": False,
            },
        }

        req = urllib.request.Request(
            init_url,
            data=json.dumps(init_body).encode(),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            init_result = json.loads(resp.read())

        upload_url = init_result.get("data", {}).get("upload_url")
        video_id = init_result.get("data", {}).get("video_id")
        if not upload_url or not video_id:
            log.error(f"TikTok init failed: {init_result}")
            return None

        # Step 2: Upload video file via chunked POST
        with open(video_path, "rb") as f:
            video_bytes = f.read()

        req = urllib.request.Request(
            upload_url,
            data=video_bytes,
            headers={"Content-Type": "video/mp4"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            upload_result = json.loads(resp.read())

        if upload_result.get("code") == 0:
            log.info(f"Uploaded to TikTok: {video_id}")
            return video_id
        else:
            log.error(f"TikTok upload failed: {upload_result}")
            return None

    except Exception as e:
        log.error(f"TikTok upload failed: {e}")
        return None

def fetch_metrics(video_id: str) -> dict | None:
    """
    Fetch engagement metrics from TikTok Insights API.
    Returns {views, likes, comments, shares} or None.
    """
    access_token = get_access_token()
    if not access_token:
        return None

    try:
        query_url = f"https://open.tiktokapis.com/v2/video/query/?video_id={video_id}"
        req = urllib.request.Request(
            query_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())

        if result.get("data"):
            video_data = result["data"]
            return {
                "views": video_data.get("view_count", 0),
                "likes": video_data.get("like_count", 0),
                "comments": video_data.get("comment_count", 0),
                "shares": video_data.get("share_count", 0),
            }
        return None
    except Exception as e:
        log.error(f"TikTok metrics fetch failed: {e}")
        return None

from pathlib import Path
