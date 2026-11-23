"""Demo, mock and sample wearable rows are never live evidence: tell them apart from real rows.

    is_mock(row_or_device, cfg=None) -> bool
    split(rows, cfg=None) -> (real rows, mock count)

Only markers the source apps really write are used (never a guessed field):

- NOOP (github.com/ryanbr/noop), whose demo seeders fill an empty store with synthetic data. The Android
  ``DemoSeeder`` pairs a demo strap whose id starts with ``demo-`` (android/app/src/main/java/com/noop/data/
  DemoSeeder.kt:70), and its Apple twin uses an id that ends in ``-demo`` (Strand/Data/AppleDemoSeeder.swift:55).
  Both write the demo dataset under the ordinary strap id and mark it only by that id's ``device`` table name,
  which ends in ``(demo)`` (DemoSeeder.kt:93, AppleDemoSeeder.swift:67).
- Open Wearables (github.com/the-momentum/open-wearables): its seed generator marks a seed user's
  ``first_name`` with the prefix ``[SEED:`` (backend/app/services/seed_data/service.py:155), the one seed
  marker its API returns (UserRead.first_name, backend/app/schemas/model_crud/user_management/user.py:117). A
  seed user's sleep sessions carry the same source as real ones (service.py:48), so no session-level marker
  exists.

Config ``mock_device_patterns`` (a list of glob patterns, default empty) adds a host's own demo or simulated
device ids or names. Matching is case-insensitive. Stdlib only; never raises.
"""
from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Iterable, Mapping, Optional

CONFIG = "mock_device_patterns"
ID_PREFIXES = ("demo-",)       # NOOP DemoSeeder.kt:70
ID_SUFFIXES = ("-demo",)       # NOOP AppleDemoSeeder.swift:55
NAME_MARK = "(demo)"           # NOOP device.name, DemoSeeder.kt:93 / AppleDemoSeeder.swift:67
SEED_PREFIX = "[seed:"         # Open Wearables user first_name, seed_data/service.py:155 (lower-cased here)
DEVICE_KEYS = ("deviceId", "device_id", "device", "id", "name")   # the fields a row names its device by
SOURCE_KEYS = ("device", "device_id")                              # Open Wearables SourceMetadata fields
USER_KEYS = ("first_name",)

LEFT_OUT = "some demo rows were left out"
ONLY_DEMO = f"no wearable data: only demo or sample rows ({LEFT_OUT})"


def patterns(cfg: Optional[Mapping]) -> tuple:
    """Config ``mock_device_patterns``: its non-blank text entries, stripped; () when unset or not a list."""
    v = cfg.get(CONFIG) if isinstance(cfg, Mapping) else None
    if not isinstance(v, list):
        return ()
    return tuple(p.strip() for p in v if isinstance(p, str) and p.strip())


def _text_is_mock(s, pats: tuple) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    t = s.strip().lower()
    if t.startswith(ID_PREFIXES) or t.endswith(ID_SUFFIXES) or t.endswith(NAME_MARK) or t.startswith(SEED_PREFIX):
        return True
    return any(fnmatchcase(t, p.lower()) for p in pats)


def is_mock(row_or_device, cfg: Optional[Mapping] = None) -> bool:
    """True when a device id or name (a str), or a row (a mapping: its device fields, an Open Wearables
    ``source`` object's device fields, a user's ``first_name``) carries a demo marker or matches a configured
    pattern. Any other field is never read; anything else is not mock."""
    pats = patterns(cfg)
    if isinstance(row_or_device, str):
        return _text_is_mock(row_or_device, pats)
    if not isinstance(row_or_device, Mapping):
        return False
    vals = [row_or_device.get(k) for k in DEVICE_KEYS + USER_KEYS]
    src = row_or_device.get("source")
    if isinstance(src, Mapping):
        vals += [src.get(k) for k in SOURCE_KEYS]
    return any(_text_is_mock(v, pats) for v in vals)


def split(rows: Iterable, cfg: Optional[Mapping] = None) -> tuple:
    """(the rows that are not mock, in order; how many were left out)."""
    real, n = [], 0
    for r in rows:
        if is_mock(r, cfg):
            n += 1
        else:
            real.append(r)
    return real, n
