# limitless

The **Limitless Protocol** as a [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin: a closed loop around one person's peak performance. Sleep, energy and recovery come first, then learning, then flow. The agent observes, suggests one small intervention, and checks what actually happened. It never prescribes.

> [!NOTE]
> This repo is code only. Your data stays on your machines: wearables, phone state and messages are read locally and never committed. Tests use synthetic fixtures, and `tests/test_public_hygiene.py` fails the suite if private paths, tokens or data files are ever committed.

## Principles
- **The pill is a system.** It's a loop, not a score: observe → one low-burden change → lock a prediction → read the outcome → revise only from evidence.
- **Foundation first.** Sleep, energy, nutrition and recovery set the ceiling for everything else.
- **Attention is the scarce resource.** Few notifications, each one useful, the key point first, one tap to act. Decisions are asked for in peak windows, reviews in troughs, and capture can happen anytime.
- **Events, not clock times.** Cues come from waking, the end of a deep-work block or wind-down, never from a fixed schedule.
- **Kind by default.** One habit a week, a start that takes 2 minutes or less, and a skipped day counts as unlogged, not failed.
- **Honest numbers.** Every value says whether it's measured, imported, a proxy or self-reported, and how old it is. Unknown ≠ No.
- **Never:** no drug or supplement advice, no clinical claims, no capability score, no unattended intervention engine.

## What's here (v0, in progress)
- `limitless/send_gate.py`: the one send policy. 12 h dedupe, a daily cap, a hold while the phone is in Sleep mode, a pending-asks digest folded into the morning brief, and internal ids removed.
- `bin/kevin-push`: the delivery CLI built on the gate (Telegram through a Hermes profile). `KEVIN_PUSH_STRICT=1` exits 3 when the message wasn't delivered.
  - Configure with `KEVIN_PUSH_PROFILE`, `KEVIN_PUSH_TO`, `LIMITLESS_STATE` or `LIMITLESS_CONFIG` (`~/.config/limitless/config.json` → `"state"`).
- `limitless/brief_post.py` + `bin/limitless-brief`: finalize and deliver the wake-up brief.
- `limitless/decision_window.py`: decision windows. A job declares `peak`, `trough`, `wind_down` or `anytime`; a provider (`StaticProvider`, `StateFileProvider`) says which window is open from events, never clock times; `decide()` returns deliver, hold or drop with a one-line reason. `send_gate.decide(..., window=...)` takes it as an optional input. Design note: [docs/decision-window.md](docs/decision-window.md).
- `scripts/replay_log.py`: replay a delivery log through the gate, read-only, counts only.

Roadmap: plugin tools (`limitless_status`, `limitless_state`, `limitless_window`, `limitless_habit`, `limitless_capture`) and a `pre_llm_call` state card. Also event-triggered jobs for the wake brief, the post-nap message and the bedtime question, offered as Hermes [Schedule cards](https://github.com/NousResearch/hermes-agent/pull/158289) and gated by decision windows. Then a weekly review and N-of-1 experiments. Data comes from adapters for [NOOP](https://github.com/kvnloo/noop) (WHOOP/Oura), Health Connect, smart-scale fusion, a REHIT bike app, ActivityWatch and Anki.

## Tests
```bash
python3 -I -m unittest discover -s tests
```

## License
MIT
