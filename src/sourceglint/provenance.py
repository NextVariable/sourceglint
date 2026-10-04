"""Display original publishing surfaces separately from retrieval adapters."""
from urllib.parse import urlsplit

_DOMAINS = {
    "reddit.com": "Reddit", "news.ycombinator.com": "Hacker News",
    "github.com": "GitHub", "youtube.com": "YouTube", "youtu.be": "YouTube",
    "producthunt.com": "Product Hunt", "x.com": "X", "twitter.com": "X",
    "bsky.app": "Bluesky", "dev.to": "DEV", "qiita.com": "Qiita",
    "arxiv.org": "arXiv", "huggingface.co": "Hugging Face",
    "stackoverflow.com": "Stack Overflow", "npmjs.com": "npm",
}


def original_platform(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    for domain, label in _DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return label
    return host or "Unidentified platform"
