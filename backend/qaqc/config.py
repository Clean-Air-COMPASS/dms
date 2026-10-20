from __future__ import annotations

from typing import Dict, List


def default_config() -> Dict[str, List[str]]:
    """Return non-policy plugin stages retained for SDK compatibility.

    Ingest checks are selected exclusively by the effective policy resolver.
    Keeping a default ingest list here would make disabled checks execute.
    """
    return {
        "ingest": [],
        "post_ingest": [],
    }
