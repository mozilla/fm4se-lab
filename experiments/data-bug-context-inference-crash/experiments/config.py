from __future__ import annotations

import os
from typing import Dict

# ============================================================
# Global configuration
# ============================================================

BUGZILLA_BASE = "https://bugzilla.mozilla.org/rest"
PHABRICATOR_BASE = "https://phabricator.services.mozilla.com"


DEEPSEEK_API_KEY = "sk-72478e7eec004bc6841a26c555a6bee8"
# 'Your key here'  # os.environ.get("DEEPSEEK_API_KEY") or
# "sk-72478e7eec004bc6841a26c555a6bee8"

DEFAULT_MODEL = "deepseek-chat"

PHAB_HEADERS: Dict[str, str] = {
    "User-Agent": "crash-missing-info3-to-reach-patch/1.0",
}
