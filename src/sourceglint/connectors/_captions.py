"""Read public timed captions advertised by yt-dlp metadata (no media download)."""

from __future__ import annotations

import html
import json
import re
from urllib.parse import urlparse


def caption_body(body: bytes, extension: str):
    segments = []
    if extension == "json3":
        payload = json.loads(body.decode("utf-8"))
        for event in payload.get("events", []):
            text = "".join(str(x.get("utf8") or "") for x in event.get("segs", []))
            text = " ".join(text.split())
            if text:
                segments.append(
                    {
                        "start_seconds": float(event.get("tStartMs") or 0) / 1000,
                        "text": text,
                    }
                )
    else:
        text = body.decode("utf-8")
        start = None
        for line in text.splitlines():
            match = re.match(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s+-->", line)
            if match:
                h, m, s, ms = match.groups()
                start = int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
            elif start is not None and line.strip() and not line.strip().isdigit():
                clean = html.unescape(re.sub(r"<[^>]+>", "", line)).strip()
                if clean:
                    segments.append({"start_seconds": start, "text": clean})
    # Rolling auto-captions repeat identical lines. Preserve distinct repeats
    # separated in time; suppress only neighboring duplicate segments.
    distinct = []
    for seg in segments:
        if distinct and distinct[-1]["text"] == seg["text"]:
            continue
        distinct.append(seg)
    return "\n".join(
        f"[{x['start_seconds']:g}s] {x['text']}" for x in distinct
    ), distinct


def fetch_captions(client, item, language="en"):
    failures = []
    attempts = 0
    for kind in ("subtitles", "automatic_captions"):
        languages = item.get(kind) or {}
        if not isinstance(languages, dict):
            continue
        keys = sorted(
            languages,
            key=lambda key: (
                not key.startswith(language),
                not key.startswith("en"),
                key,
            ),
        )
        for key in keys[:2]:
            if not isinstance(languages[key], list):
                continue
            tracks = [
                t
                for t in languages[key]
                if isinstance(t, dict) and t.get("ext") in ("json3", "vtt")
            ]
            tracks.sort(key=lambda t: t["ext"] != "json3")
            for track in tracks[:2]:
                url = str(track.get("url") or "")
                parsed = urlparse(url)
                if parsed.scheme != "https" or not (
                    parsed.hostname == "youtube.com"
                    or (parsed.hostname or "").endswith(".youtube.com")
                ):
                    continue
                if attempts >= 4:
                    return "", {"transcript_status": "unavailable", "caption_failures": failures}
                attempts += 1
                try:
                    response = client.request(url, timeout=10)
                    if getattr(response, "status", 200) != 200:
                        raise ValueError("caption HTTP failure")
                    text, segments = caption_body(response.body, track["ext"])
                except Exception as exc:
                    failures.append({"language": key, "format": track["ext"], "error_type": type(exc).__name__})
                    continue
                if text:
                    return text, {
                        "caption_failures": failures,
                        "caption_language": key,
                        "caption_kind": kind,
                        "caption_segments": segments,
                        "caption_url": url,
                    }
    return "", {"transcript_status": "unavailable", "caption_failures": failures}
