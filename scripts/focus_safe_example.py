"""The synthetic focus-safe example in docs/focus-safe.md: python3 -I scripts/focus_safe_example.py

A made-up config in a temporary dir: one protected phone (serial SYNTHETIC0001), one agent display on that
phone (display id 7, made up) and an agent X display (:99, made up), focus_safe set to warn and a temporary
audit log. It runs the real classify, the real pre_tool_call hook and the real limitless_focus_safe tool body
on a few synthetic commands at a fixed synthetic clock. No command is run, nothing is sent, and nothing is
written outside the temporary dir.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import focus_safe  # noqa: E402

NOW = datetime(2033, 3, 9, 14, 0, tzinfo=timezone.utc).timestamp()
COMMANDS = (
    "adb -s SYNTHETIC0001 shell input tap 540 1200",
    "adb -s SYNTHETIC0001 shell input -d 7 tap 540 1200",
    "adb -s SYNTHETIC0001 shell am start -n org.example.app/.Main",
    "adb -s SYNTHETIC0001 shell am start --display 7 -n org.example.app/.Main",
    "adb -s SYNTHETIC0001 shell dumpsys window",
    "adb -s SYNTHETIC0001 exec-out screencap -d 7 -p",
    "adb -s SYNTHETIC0009 shell input keyevent HOME",
    "xdotool key ctrl+l",
    "DISPLAY=:99 xdotool key ctrl+l",
    "osascript -e 'tell application \"Notes\" to activate'",
    "open -a Notes",
    "open -g -a Notes",
)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    audit = root / "audit.jsonl"
    cfg = root / "config.json"
    cfg.write_text(json.dumps({"focus_safe": "warn", "focus_safe_serials": ["SYNTHETIC0001"],
                               "focus_safe_agent_displays": ["7", ":99"], "audit_path": str(audit)}))
    os.environ.clear()
    os.environ["LIMITLESS_CONFIG"] = str(cfg)
    mode, serials, displays = focus_safe.settings(json.loads(cfg.read_text()))

    print("# classify (terminal tool)")
    for cmd in COMMANDS:
        got = focus_safe.classify("terminal", {"command": cmd}, serials, displays)
        print(f"{got['verdict']:4}  {cmd}")
        if got["verdict"] == focus_safe.WARN:
            print(f"      why: {got['why']}")

    print("# the pre_tool_call hook on every command: what it returns, the audit lines it wrote")
    hook = focus_safe.make_pre_tool_call(clock=lambda: NOW)
    returns = {repr(hook(tool_name="terminal", args={"command": c}, task_id="t")) for c in COMMANDS}
    print("returns:", ", ".join(sorted(returns)))
    for ln in audit.read_text().splitlines():
        row = json.loads(ln)
        print(json.dumps({k: row[k] for k in ("hook", "tier", "lines", "digits", "blocked")}))

    print("# the note an agent would see, if the host let a pre_tool_call hook add one")
    print(focus_safe.note(focus_safe.RULES[0]["why"]))

    print("# limitless_focus_safe")
    res = focus_safe.tool(NOW)
    print(json.dumps(dict(res, label=res["label"]["label"])))
