from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import requests


class BugzillaClient:
    def __init__(self, base_url: str = "https://bugzilla.mozilla.org"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "mozilla-resolution-trace/0.1",
                "Accept": "application/json",
            }
        )

    @staticmethod
    def parse_bug_id(bug_id: Optional[int] = None, bug_url: Optional[str] = None) -> int:
        if bug_id is not None:
            return int(bug_id)
        if not bug_url:
            raise ValueError("Either bug_id or bug_url must be provided")

        patterns = [
            r"id=(\d+)",
            r"/show_bug\.cgi\?id=(\d+)",
            r"/bug/(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, bug_url)
            if match:
                return int(match.group(1))
        raise ValueError(f"Could not parse bug id from URL: {bug_url}")

    def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = self.session.get(f"{self.base_url}/{path.lstrip('/')}", params=params, timeout=45)
        response.raise_for_status()
        return response.json()

    def _get_json_or_default(
        self,
        path: str,
        default: Any,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        try:
            return self._get_json(path, params=params)
        except requests.HTTPError as exc:
            response = exc.response
            if response is not None and response.status_code == 404:
                return default
            raise

    def get_bug(self, bug_id: int) -> Dict[str, Any]:
        payload = self._get_json(f"rest/bug/{bug_id}", params={"include_fields": "_all"})
        bugs = payload.get("bugs", [])
        if not bugs:
            raise ValueError(f"Bug {bug_id} was not found")
        return bugs[0]

    def get_comments(self, bug_id: int) -> List[Dict[str, Any]]:
        payload = self._get_json_or_default(f"rest/bug/{bug_id}/comment", default={"bugs": {}})
        return payload.get("bugs", {}).get(str(bug_id), {}).get("comments", [])

    def get_history(self, bug_id: int) -> List[Dict[str, Any]]:
        payload = self._get_json_or_default(f"rest/bug/{bug_id}/history", default={"bugs": []})
        bugs = payload.get("bugs", [])
        if not bugs:
            return []
        return bugs[0].get("history", [])

    def get_attachments(self, bug_id: int) -> List[Dict[str, Any]]:
        payload = self._get_json_or_default(
            f"rest/bug/{bug_id}/attachment",
            default={"bugs": {}},
            params={"include_fields": "_all"},
        )
        return payload.get("bugs", {}).get(str(bug_id), [])
