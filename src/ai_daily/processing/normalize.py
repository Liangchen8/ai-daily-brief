from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "source"}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(str(url).strip())
    scheme = parts.scheme.lower() or "https"
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = sorted((key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in TRACKING_PARAMS)
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def normalize_title(title: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff ]+", " ", title.lower())
    return " ".join(text.split())

