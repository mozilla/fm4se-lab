from __future__ import annotations

from typing import Any, Dict, Optional

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
