from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import requests


class MercurialClient:
    def __init__(self, base_url: str = "https://hg.mozilla.org"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "mozilla-resolution-trace/0.1",
                "Accept": "application/json",
            }
        )

    def _get_json(self, path: str) -> Optional[Dict[str, Any]]:
        response = self.session.get(f"{self.base_url}/{path.lstrip('/')}", timeout=45)
        if response.status_code >= 400:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    def _get_text(self, path: str) -> Optional[str]:
        response = self.session.get(f"{self.base_url}/{path.lstrip('/')}", timeout=45)
        if response.status_code >= 400:
            return None
        return response.text

    def get_revision(self, repo_path: str, revision: str) -> Optional[Dict[str, Any]]:
        return self._get_json(f"{repo_path}/json-rev/{revision}")

    def get_raw_changeset(self, repo_path: str, revision: str) -> Optional[str]:
        return self._get_text(f"{repo_path}/raw-rev/{revision}")

    def get_raw_file(self, repo_path: str, revision: str, file_path: str) -> Optional[str]:
        return self._get_text(f"{repo_path}/raw-file/{revision}/{file_path.lstrip('/')}")


class GitHubMirrorClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "mozilla-resolution-trace/0.1",
                "Accept": "application/vnd.github+json",
            }
        )

    def get_commit(self, owner: str, repo: str, sha: str) -> Optional[Dict[str, Any]]:
        url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}"
        response = self.session.get(url, timeout=45)
        if response.status_code >= 400:
            return None
        return response.json()


class CILogClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "mozilla-resolution-trace/0.1",
                "Accept": "text/plain, text/html, application/json;q=0.9, */*;q=0.1",
            }
        )

    def get_log(self, url: str) -> Optional[str]:
        response = self.session.get(url, timeout=45)
        if response.status_code >= 400:
            return None

        content_type = (response.headers.get("Content-Type") or "").lower()
        text = response.text
        if "text" in content_type or "json" in content_type or url.endswith((".log", ".txt")):
            return text
        return None


class SearchfoxClient:
    PATH_FIELD_RE = re.compile(r'"path":\s*"(?P<path>[^"]+)"')
    RESULT_RE = re.compile(
        r'href="/(?P<repo>[^/]+)/source/(?P<path>[^"#?]+)(?:#[^"]*)?"[^>]*>(?P<label>.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    TAG_RE = re.compile(r"<[^>]+>")

    def __init__(self, base_url: str = "https://searchfox.org"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "mozilla-resolution-trace/0.1",
                "Accept": "text/html,application/xhtml+xml",
            }
        )

    def search(self, query: str, repo: str = "mozilla-central", limit: int = 8) -> List[Dict[str, str]]:
        search_repo = {
            "mozilla-central": "firefox-main",
            "comm-central": "comm-central",
        }.get(repo, repo)
        response = self.session.get(
            f"{self.base_url}/{search_repo}/search",
            params={"q": query},
            timeout=45,
        )
        if response.status_code >= 400:
            return []
        html = response.text
        results: List[Dict[str, str]] = []
        seen = set()
        for match in self.RESULT_RE.finditer(html):
            path = match.group("path")
            repo_name = match.group("repo")
            if not path or path in seen:
                continue
            seen.add(path)
            label = self.TAG_RE.sub("", match.group("label")).strip()
            results.append(
                {
                    "repo": repo_name,
                    "path": path,
                    "label": label or path.rsplit("/", 1)[-1],
                    "url": f"{self.base_url}/{repo_name}/source/{path}",
                }
            )
            if len(results) >= limit:
                break
        if results:
            return results

        for match in self.PATH_FIELD_RE.finditer(html):
            path = match.group("path")
            if not path or path in seen:
                continue
            seen.add(path)
            results.append(
                {
                    "repo": repo,
                    "path": path,
                    "label": path.rsplit("/", 1)[-1],
                    "url": f"{self.base_url}/{search_repo}/source/{path}",
                }
            )
            if len(results) >= limit:
                break
        return results
