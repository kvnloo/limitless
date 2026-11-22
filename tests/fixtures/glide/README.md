# Glide attention fixtures (synthetic)

Shape of Glide's `<profile>/glide/attention.json`, as written by `glide/attention.py`
(`save()`, `start_block()`, `route()`, `wind_down()`) in https://github.com/kvnloo/glide at
commit daa232a55966c256b1f350b11961d4e507af33fa:

    {"block":  {"start": epoch_s, "end": epoch_s, "minutes": int} | null,
     "queue":  [{"title": str, "body": str, "cls": str, "at": epoch_s}],
     "resume": {"saved": epoch_s, "night": "YYYY-MM-DD", "session_id": str, "title": str,
                "last_asks": [str], "queued": int} | null,
     "nudged": "YYYY-MM-DD" | ""}

All values are made up. Every timestamp is anchored at 1894708800 (the event the fixture is
about); tests shift the whole file to place that event at any hour.

- `focus-block.json`: a 50-minute `/glide focus start` block that began at the anchor, one ask held.
- `wind-down.json`: the wind-down nudge fired at the anchor (`resume.saved`), no block.
- `idle.json`: Glide's empty state: no block, no wind-down.
- `malformed.json`: truncated JSON.
