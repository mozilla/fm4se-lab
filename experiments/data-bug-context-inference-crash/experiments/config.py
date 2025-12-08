from __future__ import annotations

import os
from typing import Dict

# ============================================================
# Global configuration
# ============================================================

BUGZILLA_BASE = "https://bugzilla.mozilla.org/rest"
PHABRICATOR_BASE = "https://phabricator.services.mozilla.com"


DEEPSEEK_API_KEY = 'Your key here'  

DEFAULT_MODEL = "deepseek-chat"

PHAB_HEADERS: Dict[str, str] = {
    "User-Agent": "crash-missing-info3-to-reach-patch/1.0",
}
