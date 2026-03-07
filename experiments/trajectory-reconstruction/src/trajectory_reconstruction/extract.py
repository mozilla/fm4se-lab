from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse


URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
DIFF_RE = re.compile(r"\bD(\d{2,})\b")
HG_REV_RE = re.compile(r"https?://hg\.mozilla\.org/([^\s/]+(?:/[^\s/]+)*)/rev/([a-f0-9]{12,40})")
HG_RAW_RE = re.compile(r"https?://hg\.mozilla\.org/([^\s/]+(?:/[^\s/]+)*)/raw-rev/([a-f0-9]{12,40})")
BUG_RE = re.compile(r"\bbug\s+#?(\d{5,8})\b", re.IGNORECASE)
SEARCHFOX_PATH_RE = re.compile(r"/source/([^#?\s]+)")


@dataclass
class ArtifactLink:
    artifact_type: str
    url: str
    identifier: str


def extract_urls(text: str) -> List[str]:
    return URL_RE.findall(text or "")


def classify_url(url: str) -> Optional[ArtifactLink]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if "bugzilla.mozilla.org" in host and "show_bug.cgi" in parsed.path + "?" + parsed.query:
        return ArtifactLink("bugzilla", url, _extract_query_id(url) or "bugzilla-link")
    if "phabricator.services.mozilla.com" in host:
        did = extract_differential_ids(url)
        if did:
            return ArtifactLink("phabricator", url, f"D{did[0]}")
        return ArtifactLink("phabricator", url, "unknown")
    if "lando" in host and "mozilla" in host:
        return ArtifactLink("lando", url, "lando-link")
    if "hg.mozilla.org" in host:
        m = HG_REV_RE.search(url) or HG_RAW_RE.search(url)
        if m:
            repo, rev = m.groups()
            return ArtifactLink("mercurial", url, f"{repo}:{rev}")
        return ArtifactLink("mercurial", url, "hg-link")
    if "searchfox.org" in host:
        sm = SEARCHFOX_PATH_RE.search(url)
        return ArtifactLink("searchfox", url, sm.group(1) if sm else "searchfox-link")
    if "treeherder.mozilla.org" in host:
        return ArtifactLink("treeherder", url, "treeherder-link")
    return None


def _extract_query_id(url: str) -> Optional[str]:
    m = re.search(r"id=(\d+)", url)
    return m.group(1) if m else None


def extract_differential_ids(text: str) -> List[int]:
    return sorted({int(m) for m in DIFF_RE.findall(text or "")})


def extract_hg_revisions(text: str) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    for m in HG_REV_RE.finditer(text or ""):
        repo, rev = m.groups()
        out.append((repo, rev, m.group(0)))
    for m in HG_RAW_RE.finditer(text or ""):
        repo, rev = m.groups()
        out.append((repo, rev, m.group(0)))

    unique = []
    seen = set()
    for item in out:
        key = (item[0], item[1])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def extract_bug_mentions(text: str) -> List[int]:
    return sorted({int(m) for m in BUG_RE.findall(text or "")})


def collect_links_from_texts(texts: Sequence[str]) -> List[ArtifactLink]:
    links: List[ArtifactLink] = []
    seen = set()
    for text in texts:
        for url in extract_urls(text):
            classified = classify_url(url)
            if not classified:
                continue
            key = (classified.artifact_type, classified.url)
            if key not in seen:
                seen.add(key)
                links.append(classified)
    return links


def safe_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""


def maybe(value: object, fallback: str = "Unknown from available Mozilla artifacts.") -> str:
    if value is None:
        return fallback
    if isinstance(value, str) and not value.strip():
        return fallback
    return str(value)
