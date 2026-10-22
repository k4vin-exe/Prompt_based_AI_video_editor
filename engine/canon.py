"""
engine/canon.py
---------------
Canonical JSON serialisation and timeline_hash computation.  (R-HIST-06)

Rules for canonical form:
  - All dict keys sorted alphabetically (json.dumps sort_keys=True)
  - All times are integers (µs)
  - Op IDs are sequential integers (never UUIDs)
  - No timestamps, random seeds, or non-deterministic values
  - sha256 of utf-8-encoded canonical JSON

The hash is computed over the Timeline (the result of fold()), not over
the ops themselves. This means it reflects the *observable* output, so
two different op sequences that produce the same timeline have the same hash.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    """
    Produce a deterministic JSON string from any JSON-serialisable object.
    - sort_keys=True ensures key order is deterministic
    - separators=(',', ':') removes whitespace for a compact, unique form
    - ensure_ascii=False preserves Unicode (hashed as utf-8 below)
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def timeline_hash(timeline_dict: dict) -> str:
    """
    Compute sha256 hash of the canonical JSON of a timeline dict.
    Input should be the result of Timeline.to_dict().

    Same timeline_dict -> same hash, always.  (R-HIST-06)
    """
    cjson = canonical_json(timeline_dict)
    return hashlib.sha256(cjson.encode("utf-8")).hexdigest()


def verify_determinism(hash1: str, hash2: str, hash3: str) -> bool:
    """Return True if all three hashes are identical (determinism check)."""
    return hash1 == hash2 == hash3
