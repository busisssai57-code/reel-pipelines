"""YouTube Data API integration: upload video, fetch metrics."""
from __future__ import annotations
import logging
from . import config, db

log = logging.getLogger("youtube_api")

def get_client():
    """
    Load YouTube API client using stored token from db.
    Requires prior OAuth setup via setup-oauth.ps1.
    """
    try:
        from googleapiclient.discovery import build
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        log.error("google-api-python-client not installed; skipping YouTube")
        return None

    token_data = db.get_platform_token("youtube")
    if not token_data:
        log.warning("No YouTube token stored; run setup-oauth.ps1 youtube")
        return None

    try:
        creds = Credentials(
            token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=config.YOUTUBE_CLIENT_ID,
            client_secret=config.YOUTUBE_CLIENT_SECRET,
        )

        # Refresh if near expiry
        if creds.expired:
            req = Request()
            creds.refresh(req)
            db.set_platform_token(
                "youtube",
                creds.token,
                creds.refresh_token,
                creds.expiry.timestamp() if creds.expiry else None,
                "https://www.googleapis.com/auth/youtube.upload",
            )

        return build("youtube", "v3", credentials=creds)
    except Exception as e:
        log.error(f"Failed to build YouTube client: {e}")
        return None

def upload_video(draft: dict) -> str | None:
    """
    Upload video to YouTube using Data API resumable upload.
    Returns youtube_video_id or None on failure.
    """
    client = get_client()
    if not client:
        return None

    try:
        video_path = draft.get("video_path")
        if not video_path:
            return None

        body = {
            "snippet": {
                "title": draft.get("title", f"Reel {draft.get('id')}"),
                "description": draft.get("script", draft.get("topic", "")),
                "tags": ["ai", "mrbeast", draft.get("category", "").lower()],
                "categoryId": "24",  # Entertainment
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        with open(video_path, "rb") as f:
            request = client.videos().insert(
                part="snippet,status",
                body=body,
                media_body=f,
            )
            response = request.execute()
            video_id = response.get("id")
            log.info(f"Uploaded to YouTube: {video_id}")
            return video_id

    except Exception as e:
        log.error(f"YouTube upload failed: {e}")
        return None

def fetch_metrics(video_id: str) -> dict | None:
    """
    Fetch engagement metrics from YouTube Analytics API.
    Returns {views, likes, comments, ctr} or None.
    """
    client = get_client()
    if not client:
        return None

    try:
        # YouTube Analytics API requires additional setup; for now,
        # use YouTube Data API statistics endpoint (limited but available)
        request = client.videos().list(
            part="statistics",
            id=video_id,
        )
        response = request.execute()
        if response.get("items"):
            stats = response["items"][0].get("statistics", {})
            return {
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "ctr": 0.0,  # not available via Data API (requires Analytics API)
            }
        return None
    except Exception as e:
        log.error(f"YouTube metrics fetch failed: {e}")
        return None
