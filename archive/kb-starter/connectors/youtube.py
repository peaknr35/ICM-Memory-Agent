"""YouTube connector — latest uploads (title + description) via the Data API,
plus transcripts where available. One doc per video. Channel handle comes
from config.json.
"""
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

API = "https://www.googleapis.com/youtube/v3"


def _key():
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("No YOUTUBE_API_KEY in env")
    return key


def _get(path, **params):
    params["key"] = _key()
    resp = requests.get(f"{API}/{path}", params=params, timeout=30)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "unknown"))
    return data


def _transcript(video_id):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        segments = YouTubeTranscriptApi().fetch(video_id)
        return " ".join(s.text for s in segments)
    except Exception:
        return ""


def fetch(max_videos=None, transcripts=None):
    cfg = config.load().get("youtube", {})
    handle = cfg["handle"]
    max_videos = max_videos or cfg.get("max_videos", 30)
    transcripts = transcripts if transcripts is not None else cfg.get("transcripts", 10)
    ch = _get("channels", part="contentDetails,snippet", forHandle=handle)["items"][0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    channel_name = ch["snippet"]["title"]
    items, page = [], None
    while len(items) < max_videos:
        data = _get("playlistItems", part="snippet,contentDetails", playlistId=uploads,
                    maxResults=min(50, max_videos - len(items)), **({"pageToken": page} if page else {}))
        items += data["items"]
        page = data.get("nextPageToken")
        if not page:
            break
    docs = []
    for i, item in enumerate(items):
        sn = item["snippet"]
        vid = item["contentDetails"]["videoId"]
        transcript = _transcript(vid) if i < transcripts else ""
        content = sn.get("description", "")
        if transcript:
            content += f"\n\n--- transcript ---\n{transcript[:30000]}"
        docs.append(dict(
            source="youtube", source_id=vid, ts=sn["publishedAt"],
            title=sn["title"], content=content,
            metadata={"channel": channel_name, "url": f"https://youtu.be/{vid}",
                      "has_transcript": bool(transcript)},
        ))
    print(f"  {channel_name}: {len(docs)} videos ({min(transcripts, len(docs))} with transcripts)")
    return docs
