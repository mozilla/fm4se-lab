from __future__ import annotations

import requests

from .config import PHABRICATOR_BASE, PHAB_HEADERS


def fetch_raw_diff(revision_id: int, patch_id: int | None = None) -> str:
    if patch_id is None:
        url = f"{PHABRICATOR_BASE}/D{revision_id}?download=true"
    else:
        url = f"{PHABRICATOR_BASE}/D{revision_id}?id={patch_id}&download=true"

    resp = requests.get(url, headers=PHAB_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text
