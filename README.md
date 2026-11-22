# hermes-limitless

Private. The Limitless Protocol as a Hermes plugin. Code only; no personal data (tests use synthetic fixtures).

- `limitless/send_gate.py`: the one send policy (12 h dedupe, 6/day cap, Sleep-mode hold, asks digest folded into the brief, card ids removed).
- `bin/kevin-push`: the only delivery path to Kevin (Telegram), built on the gate. `KEVIN_PUSH_STRICT=1` exits 3 when not delivered.
- `scripts/replay_log.py`: replay a real kevin-push log through the gate, read-only, counts only.

Tests: `python3 -I -m unittest discover -s tests`
