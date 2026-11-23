"""A synthetic week review before and after message_shape, the way bin/kevin-push delivers it.

    python3 -I scripts/message_shape_example.py

Synthetic: the week review with every optional line, each from its own module's words (the same builder as
tests/test_message_shape_contract.py). No real data.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from limitless import message_shape, send_gate  # noqa: E402
from test_message_shape_contract import week_review_body  # noqa: E402


def show(label, text):
    print(f"{label}:")
    for ln in text.splitlines():
        print(f"  {ln}")


def main():
    before = send_gate.outgoing(week_review_body(), send_gate.why_line("habit cue event"))
    after, folded, cut = message_shape.fit("Week review", before, message_shape.limits({}))
    show("before", before)
    show("after", after)
    print(f"audit row: folded {message_shape.count_words(folded)}, cut {message_shape.count_words(cut)}")


if __name__ == "__main__":
    main()
