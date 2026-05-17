"""JSON file persistence for the MatchStore.

Atomic write via tempfile + os.replace. On load failure, returns an empty
store and logs a warning rather than crashing — the user can start scoring
a fresh match without manually deleting a broken state file.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, fields, is_dataclass
from typing import Any, Type, TypeVar

from . import state as S

log = logging.getLogger(__name__)

T = TypeVar("T")


def _dataclass_from_dict(cls: Type[T], data: dict) -> T:
    """Recursively build a dataclass tree from nested dicts/lists."""
    if not is_dataclass(cls):
        return data
    kwargs = {}
    type_hints = {f.name: f.type for f in fields(cls)}
    for f in fields(cls):
        if f.name not in data:
            continue
        val = data[f.name]
        # Resolve string type hints (from `from __future__ import annotations`)
        hint = type_hints[f.name]
        if isinstance(hint, str):
            hint_s = hint
        else:
            hint_s = str(hint)
        if val is None:
            kwargs[f.name] = val
        elif "List[" in hint_s and isinstance(val, list):
            inner = hint_s.split("List[", 1)[1].rsplit("]", 1)[0]
            inner_cls = getattr(S, inner, None)
            if inner_cls and is_dataclass(inner_cls):
                kwargs[f.name] = [_dataclass_from_dict(inner_cls, v) for v in val]
            else:
                kwargs[f.name] = val
        else:
            kwargs[f.name] = val
    return cls(**kwargs)


def load_store(path: str) -> S.MatchStore:
    if not os.path.exists(path):
        return S.MatchStore()
    try:
        with open(path, "r") as f:
            raw = json.load(f)
    except Exception as e:
        log.warning("Failed to read %s (%s) — starting with empty store", path, e)
        return S.MatchStore()
    try:
        matches = {}
        for k, v in raw.get("matches", {}).items():
            md = _dataclass_from_dict(S.MatchDetail, v)
            matches[int(k)] = md
        return S.MatchStore(
            matches=matches,
            active_match_id=raw.get("active_match_id"),
            next_id=raw.get("next_id", 9000001),
        )
    except Exception as e:
        log.warning("Failed to parse %s (%s) — starting with empty store", path, e)
        return S.MatchStore()


def save_store(store: S.MatchStore, path: str) -> None:
    raw = {
        "matches": {str(k): asdict(v) for k, v in store.matches.items()},
        "active_match_id": store.active_match_id,
        "next_id": store.next_id,
    }
    dirname = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(dirname, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=dirname)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(raw, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
