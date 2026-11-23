"""The skill tree's synthetic example for docs/skill-tree.md: a temp state dir, two decided weeks and a running
one, then limitless_skill_tree and limitless_card_view kind skill_tree. Synthetic records only.

    python3 -I scripts/skill_tree_example.py           # rewrite docs/examples/skill-tree.html
    python3 -I scripts/skill_tree_example.py --print   # print the output docs/skill-tree.md shows
    python3 -I scripts/skill_tree_example.py --check   # exit 1 when the committed card is out of date
"""
import json
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import card_view, habit_catalogue, stop_rule, tools  # noqa: E402

NOW = 1894708800.0                   # a fixed synthetic clock (the test fixtures' now)
TODAY = date.fromtimestamp(NOW)
CAT = habit_catalogue.CATALOGUE
CARD = ROOT / "docs" / "examples" / "skill-tree.html"


def build(root: Path):
    st = root / "state"
    st.mkdir()
    for habit, decision, week_of in ((CAT[0]["name"], "Keep", "2029-12-25"), (CAT[1]["name"], "Drop", "2030-01-01")):
        stop_rule.record_loop(st, {"habit": habit, "week_of": week_of, "checkins": {week_of: "Done"}},
                              decision, f"{week_of}T09:00:00+00:00", now=NOW)
    (st / "habit.json").write_text(json.dumps({"habit": CAT[2]["name"], "week_of": TODAY.isoformat(),
                                               "checkins": {}}))
    env = {"LIMITLESS_CONFIG": str(root / "no-config.json"), "LIMITLESS_CARD_DIR": str(root / "cards")}
    tree = tools.skill_tree(st, NOW, TODAY)
    card = card_view.view(st, NOW, TODAY, "skill_tree", env=env, home=root)
    html = Path(card["value"]["path"]).read_text(encoding="utf-8")
    card["value"]["path"] = "<card dir>/" + Path(card["value"]["path"]).name
    return tree, card, html


def main(argv) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tree, card, html = build(Path(tmp))
    if "--print" in argv:
        print("## limitless_skill_tree: value.layers, one per line")
        for layer in tree["value"]["layers"]:
            print(json.dumps(layer, ensure_ascii=False))
        print("## limitless_skill_tree: the rest of the envelope")
        print(json.dumps({k: v for k, v in tree.items() if k != "value"}, indent=2, ensure_ascii=False))
        print("## limitless_card_view kind skill_tree")
        print(json.dumps(card, indent=2, ensure_ascii=False))
        print("## the card's rows (chip, then text)")
        for chip, text in re.findall(r'<span class="chip">([^<]*)</span><span class="text">([^<]*)</span>', html):
            print(f"[{chip}] {text}")
        return 0
    if "--check" in argv:
        if not CARD.is_file() or CARD.read_text(encoding="utf-8") != html:
            print("out of date: docs/examples/skill-tree.html")
            return 1
        return 0
    CARD.parent.mkdir(parents=True, exist_ok=True)
    CARD.write_text(html, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
