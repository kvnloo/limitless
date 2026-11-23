"""Render the synthetic example cards under docs/examples/ (docs/ui-card.md). Synthetic lines only.

    python3 -I scripts/ui_card_example.py          # rewrite docs/examples/ui-card-*.html
    python3 -I scripts/ui_card_example.py --check  # exit 1 when a committed example is out of date
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import ui_card  # noqa: E402

STATE = ["window: peak (proxy)",
         "post-wake peak: open",
         "sleep short (proxy); readiness unknown (no digest in the last day)",
         "habit this week: walk after lunch; today Done; target reached this week",
         "not recording: scale",
         "asks waiting on you",
         "focused mode: answer briefly, hold non-urgent asks"]
WEEK = ["Walk after lunch: 4 of 5 logged days this week.",      # digits: dropped and counted
        "habit: target reached this week",
        "Flow: deep work 300 min this week (240 min last week).",  # digits: dropped and counted
        "Rides this week: two, more than last week.",
        "Sleep: wearable on most nights; phone proxy says about the same; wearable says sleep times steady.",
        "Your rule says: keep it"]
EXAMPLES = {"ui-card-state.html": ("Today", STATE, "state"), "ui-card-week.html": ("This week", WEEK, "week")}


def main(argv) -> int:
    out = ROOT / "docs" / "examples"
    stale = []
    for name, (title, lines, kind) in EXAMPLES.items():
        html = ui_card.render(title, lines, kind, env={})["html"]
        p = out / name
        if "--check" in argv:
            if not p.is_file() or p.read_text(encoding="utf-8") != html:
                stale.append(name)
            continue
        out.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
    for name in stale:
        print(f"out of date: docs/examples/{name}")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
