"""The synthetic local model labeler example in docs/privacy-tiers.md: python3 -I scripts/t1_local_example.py

A fake llama.cpp-style binary (a small script written into a temporary dir that prints canned text) and a
made-up empty model file, tiny-model.gguf, stand in for a real model: nothing is downloaded and no model runs.
LocalModelLabeler runs bin/limitless-t1-local as its command (LIMITLESS_T1_CMD), once per canned answer, then
the doctor's local labeler row is shown with the files present and with the model file gone. Reads no real
state, writes nothing outside the temporary dir, sends nothing.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import doctor, labeler  # noqa: E402

FAKE = "#!{python} -I\nimport os\nimport time\nsay = os.environ['FAKE_SAYS']\nif say == 'SLOW':\n    " \
       "time.sleep(30)\nprint(say)\n"
CASES = [("The night was ok.", "the model says an allowed word"), ("banana", "the model says no allowed word"),
         ("7 hours", "the model says a digit"), ("SLOW", "the model runs past the timeout")]

for k in [k for k in os.environ if k.startswith("LIMITLESS_")]:
    del os.environ[k]

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    os.environ["HOME"] = str(root)
    fake = root / "llama-cli"
    fake.write_text(FAKE.format(python=sys.executable))
    fake.chmod(0o755)
    model = root / "tiny-model.gguf"
    model.write_bytes(b"")
    cfg = {"t1_model_cmd": f'"{sys.executable}" -I "{REPO / "bin" / "limitless-t1-local"}"',
           "t1_bin": str(fake), "t1_model": str(model), "t1_threads": 2, "t1_timeout_s": 1}
    path = root / "config.json"
    path.write_text(json.dumps(cfg))
    os.environ["LIMITLESS_CONFIG"] = str(path)
    print(f"rule label for sleep_h 5.3: {labeler.rule_label('sleep_h', 5.3)}")
    for says, what in CASES:
        os.environ["FAKE_SAYS"] = says
        got = labeler.from_config().label("sleep_h", 5.3, "proxy")["label"]
        note = "" if got != labeler.rule_label("sleep_h", 5.3) else " (the rule label)"
        print(f"{what}: local label: {got}{note}")
    print(doctor.text([doctor.local_labeler_row(cfg)]))
    model.unlink()
    print(doctor.text([doctor.local_labeler_row(cfg)]))
