from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import requests


DEFAULT_HEADERS = {
    "User-Agent": "trajectory-reconstruction-agent/1.0",
    "Accept": "application/json",
}


class BaseClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        response = self.session.get(url, params=params, timeout=40)
        response.raise_for_status()
        return response.json()

    def _get_text(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[str]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        response = self.session.get(url, params=params, timeout=40)
        response.raise_for_status()
        return response.text


class BugzillaClient(BaseClient):
    def __init__(self):
        super().__init__("https://bugzilla.mozilla.org")

    def get_bug(self, bug_id: int) -> Optional[Dict[str, Any]]:
        data = self._get_json(f"rest/bug/{bug_id}", params={"include_fields": "_all"})
        bugs = (data or {}).get("bugs", [])
        return bugs[0] if bugs else None

    def get_comments(self, bug_id: int) -> List[Dict[str, Any]]:
        data = self._get_json(f"rest/bug/{bug_id}/comment") or {}
        return data.get("bugs", {}).get(str(bug_id), {}).get("comments", [])

    def get_history(self, bug_id: int) -> List[Dict[str, Any]]:
        data = self._get_json(f"rest/bug/{bug_id}/history") or {}
        bugs = data.get("bugs", [])
        return bugs[0].get("history", []) if bugs else []

    def get_attachments(self, bug_id: int) -> List[Dict[str, Any]]:
        data = self._get_json(f"rest/bug/{bug_id}/attachment", params={"include_fields": "_all"}) or {}
        return data.get("bugs", {}).get(str(bug_id), [])


class PhabricatorClient(BaseClient):
    def __init__(self):
        super().__init__("https://phabricator.services.mozilla.com")
        self.token = os.environ.get("PHABRICATOR_TOKEN")

    def _conduit(self, method: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        payload_params = dict(params or {})
        if self.token:
            payload_params["__conduit__"] = {"token": self.token}

        data = {
            "params": json.dumps(payload_params),
            "output": "json",
        }

        response = self.session.post(
            f"{self.base_url}/api/{method}",
            data=data,
            timeout=40,
            headers={"User-Agent": DEFAULT_HEADERS["User-Agent"]},
        )
        response.raise_for_status()
        content = response.json()
        if content.get("error_code"):
            return None
        return content.get("result")

    def search_revisions_by_bug_id(self, bug_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        queries = [f"Bug {bug_id}", str(bug_id)]
        found: Dict[str, Dict[str, Any]] = {}

        for query in queries:
            result = self._conduit(
                "differential.revision.search",
                {
                    "constraints": {"query": query},
                    "limit": limit,
                },
            )
            for item in (result or {}).get("data", []):
                phid = item.get("phid")
                title = (item.get("fields") or {}).get("title", "")
                summary = (item.get("fields") or {}).get("summary", "")
                if str(bug_id) in title or str(bug_id) in summary:
                    if phid:
                        found[phid] = item
        return list(found.values())

    def get_revision_by_id(self, revision_id: int) -> Optional[Dict[str, Any]]:
        result = self._conduit(
            "differential.revision.search",
            {
                "constraints": {"ids": [revision_id]},
                "limit": 1,
            },
        )
        data = (result or {}).get("data", [])
        return data[0] if data else None

    def get_diff_metadata(self, revision_phid: str) -> List[Dict[str, Any]]:
        result = self._conduit(
            "differential.diff.search",
            {
                "constraints": {"revisionPHIDs": [revision_phid]},
                "limit": 50,
            },
        )
        return (result or {}).get("data", [])

    def get_raw_diff(self, diff_id: int) -> Optional[str]:
        raw = self._conduit("differential.getrawdiff", {"diffID": diff_id})
        return raw if isinstance(raw, str) else None

    def get_transactions_for_revision(self, revision_id: int) -> List[Dict[str, Any]]:
        result = self._conduit(
            "transaction.search",
            {
                "objectIdentifier": f"D{revision_id}",
                "limit": 100,
            },
        )
        return (result or {}).get("data", [])


class MercurialClient(BaseClient):
    def __init__(self):
        super().__init__("https://hg.mozilla.org")

    def get_revision(self, repo_path: str, revision: str) -> Optional[Dict[str, Any]]:
        try:
            return self._get_json(f"{repo_path}/json-rev/{revision}")
        except Exception:
            return None

    def get_raw_changeset(self, repo_path: str, revision: str) -> Optional[str]:
        try:
            return self._get_text(f"{repo_path}/raw-rev/{revision}")
        except Exception:
            return None


class SearchfoxClient(BaseClient):
    def __init__(self):
        super().__init__("https://searchfox.org")

    def search(self, query: str, repo: str = "mozilla-central") -> List[Dict[str, Any]]:
        # Intentionally disabled: this project is configured for API-only collection,
        # and Searchfox does not have a stable JSON API endpoint in this workflow.
        return []
