"""The synthetic result tier example in docs/result-tier.md: python3 -I scripts/result_tier_example.py

A made-up config in a temporary dir: t0_tools lists one made-up MCP server (mcp__synthetic_health__*) and one
made-up tool (fake_vitals), with a temporary audit log. It runs the real transform_tool_result callback and the
real limitless_result_tier tool body on made-up tool names and made-up readings at a fixed synthetic clock.
Nothing is sent and nothing is written outside the temporary dir.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import result_tier  # noqa: E402

NOW = datetime(2033, 3, 9, 14, 0, tzinfo=timezone.utc).timestamp()
CALLS = (
    ("mcp__synthetic_health__get_night", "ok", json.dumps(
        {"night": {"start": "2033-03-08T23:12:00Z", "resting_hr": 58, "hrv_ms": 41.5, "spo2_pct": 96},
         "stages_min": [64, 212, 98], "id": 77120, "note": "woke 2 times"})),
    ("fake_vitals", "ok", "weight 70.4 kg, systolic/diastolic 117/74, read at 07:45"),
    ("mcp__synthetic_health__get_night", "error", "upstream timed out after 30 s"),
    ("mcp__synthetic_weather__get_today", "ok", "high 14 C, rain 40%"),
)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    audit = root / "audit.jsonl"
    cfg = root / "config.json"
    cfg.write_text(json.dumps({"t0_tools": ["mcp__synthetic_health__*", "fake_vitals"], "audit_path": str(audit)}))
    os.environ.clear()
    os.environ["LIMITLESS_CONFIG"] = str(cfg)
    hook = result_tier.make_transform_tool_result(clock=lambda: NOW)

    print("# transform_tool_result (config t0_tools: mcp__synthetic_health__*, fake_vitals)")
    for name, status, result in CALLS:
        out = hook(tool_name=name, args={}, result=result, duration_ms=5, status=status, error_type=None,
                   error_message=None, task_id="t", session_id="s", tool_call_id="c", turn_id="u")
        print(f"tool: {name} (status {status})")
        print(f"before: {result}")
        print(f"after: {out}" if out is not None else "after: unchanged (None)")
    print()
    print("# audit rows (one per replaced result; the glob and the count, never a value)")
    for ln in audit.read_text().splitlines():
        row = json.loads(ln)
        print(json.dumps({k: row[k] for k in ("hook", "glob", "replaced", "tier", "digits", "sha256")}))
    print()
    print("# limitless_result_tier")
    print(json.dumps(result_tier.tool(), ensure_ascii=False))
    cfg.write_text(json.dumps({}))
    print(json.dumps(result_tier.tool()["label"]["label"]))
