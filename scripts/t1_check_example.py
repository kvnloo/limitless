"""The synthetic local model check example in docs/privacy-tiers.md: python3 -I scripts/t1_check_example.py

Fake model scripts written into a temporary dir stand in for a model (nothing is downloaded and no model runs):
one gives the rule's word except on owner_message_age_h, where it says the other allowed word; one always says a
wrong allowed word. bin/limitless-t1-check runs against each, as an operator would run it, with a synthetic
config whose state dir and check file are in the temporary dir; then the doctor's local labeler row and the
labeler's command are shown for each saved result. Reads no real state, sends nothing.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import doctor, labeler  # noqa: E402

FAKE = """#!{python} -I
import re, sys
sys.path.insert(0, {repo!r})
from limitless import labeler
prompt = sys.stdin.read()
kind = re.search(r"Label one (\\S+) value", prompt).group(1)
allowed = re.search(r"from this set: ([^\\n]*?)\\.\\n", prompt).group(1).split(", ")
rule = labeler.rule_label(kind, float(re.search(r"Value: (\\S+)", prompt).group(1)))
wrong = [w for w in allowed if w != rule][0]
print(wrong if sys.argv[1] == "wrong" or kind == "owner_message_age_h" else rule)
"""
EXIT = {0: "zero", 1: "one"}

for k in [k for k in os.environ if k.startswith("LIMITLESS_")]:
    del os.environ[k]

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    os.environ["HOME"] = str(root)
    state = root / "state"
    state.mkdir()
    fake = root / "fake-model"
    fake.write_text(FAKE.format(python=sys.executable, repo=str(REPO)))
    fake.chmod(0o755)
    path = root / "config.json"
    os.environ["LIMITLESS_CONFIG"] = str(path)

    def run(what, cmd, *args):
        cfg = {"state": str(state), "t1_check_file": "t1-check.txt"}
        if cmd:
            cfg["t1_model_cmd"] = cmd
        path.write_text(json.dumps(cfg))
        print(f"$ limitless-t1-check   # {what}")
        r = subprocess.run([sys.executable, "-I", str(REPO / "bin" / "limitless-t1-check")],
                           capture_output=True, text=True, timeout=120, env=dict(os.environ))
        print(r.stdout, end="")
        print(f"exit status: {EXIT.get(r.returncode, 'other')}")
        show(cfg)

    def show(cfg):
        print(doctor.text([doctor.local_labeler_row(cfg)]))
        print(f"the labeler uses the model: {'yes' if labeler.from_config().cmd else 'no'}")

    print("# before any check, with t1_check_file set:")
    first = {"state": str(state), "t1_check_file": "t1-check.txt", "t1_model_cmd": f'"{fake}" mostly'}
    path.write_text(json.dumps(first))
    show(first)
    run("a fake model that is wrong on one kind", f'"{fake}" mostly')
    run("a fake model that always says a wrong allowed word", f'"{fake}" wrong')
    run("no model command set", None)
