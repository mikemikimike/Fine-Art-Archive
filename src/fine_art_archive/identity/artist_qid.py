"""Pure sidecar helpers for reading artist Wikidata Q-IDs without API imports."""

from __future__ import annotations

import re
from typing import Any

_QID_RE = re.compile(r"^Q[0-9]+$")


def artist_qid(meta: dict[str, Any]) -> str | None:
    """The artist Q-ID a sidecar carries, or None when it carries none.

    Prefers the resolver's canonical Q-ID and falls back to the raw one, so an
    artist whose name is spelled two ways still resolves to a single Q-ID.
    """
    artist = meta.get("artist")
    if not isinstance(artist, dict):
        return None
    canonical = artist.get("canonical")
    canonical_qid = canonical.get("wikidata_q") if isinstance(canonical, dict) else None
    raw_qid = artist.get("wikidata_q")
    qid = (
        canonical_qid
        if isinstance(canonical_qid, str) and _QID_RE.fullmatch(canonical_qid)
        else raw_qid
    )
    return qid if isinstance(qid, str) and _QID_RE.fullmatch(qid) else None
