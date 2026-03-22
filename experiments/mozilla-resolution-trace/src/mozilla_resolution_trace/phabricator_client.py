from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import requests
import dotenv


dotenv.load_dotenv()


class PhabricatorClient:
    def __init__(self, base_url: str = "https://phabricator.services.mozilla.com", token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.token = token or os.getenv("PHABRICATOR_TOKEN")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "mozilla-resolution-trace/0.1",
                "Accept": "application/json",
            }
        )

    def _conduit(self, method: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any] | str]:
        payload_params = dict(params or {})
        if self.token:
            payload_params["__conduit__"] = {"token": self.token}

        response = self.session.post(
            f"{self.base_url}/api/{method}",
            data={
                "params": json.dumps(payload_params),
                "output": "json",
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error_code"):
            return None
        return payload.get("result")

    def get_revision_by_id(self, revision_id: int) -> Optional[Dict[str, Any]]:
        result = self._conduit(
            "differential.revision.search",
            {
                "constraints": {"ids": [revision_id]},
                "limit": 1,
            },
        )
        data = (result or {}).get("data", []) if isinstance(result, dict) else []
        return data[0] if data else None

    def get_diff_metadata(self, revision_phid: str) -> List[Dict[str, Any]]:
        result = self._conduit(
            "differential.diff.search",
            {
                "constraints": {"revisionPHIDs": [revision_phid]},
                "limit": 50,
            },
        )
        if not isinstance(result, dict):
            return []
        return result.get("data", [])

    def get_raw_diff(self, diff_id: int) -> Optional[str]:
        raw = self._conduit("differential.getrawdiff", {"diffID": diff_id})
        return raw if isinstance(raw, str) else None
