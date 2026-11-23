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
- The Hermes plugin: six read-mostly tools and a `pre_llm_call` state card (see [Tools and hook](#tools-and-hook)).
- `limitless/send_gate.py`: the one send policy. 12 h dedupe, a daily cap, a hold while the phone is in Sleep mode, a pending-asks digest folded into the morning brief, and internal ids removed.
- `bin/kevin-push`: the delivery CLI built on the gate (Telegram through a Hermes profile). `KEVIN_PUSH_STRICT=1` exits 3 when the message wasn't delivered.
  - Configure with `KEVIN_PUSH_PROFILE`, `KEVIN_PUSH_TO`, `LIMITLESS_STATE` or `LIMITLESS_CONFIG` (`~/.config/limitless/config.json` → `"state"`).
- `limitless/brief_post.py` + `bin/limitless-brief`: finalize and deliver the wake-up brief.
- `limitless/decision_window.py`: decision windows. A job declares `peak`, `trough`, `wind_down` or `anytime`; a provider (`StaticProvider`, `StateFileProvider`) says which window is open from events, never clock times; `decide()` returns deliver, hold or drop with a one-line reason. `send_gate.decide(..., window=...)` takes it as an optional input. Design note: [docs/decision-window.md](docs/decision-window.md).
- `limitless/glide_provider.py` + `limitless/window_chain.py`: `first_known(GlideProvider, EventProvider)` reads the window from [Glide](https://github.com/kvnloo/glide) first (a focus block is `peak` with asks held, the wind-down nudge is `wind_down`; path from `LIMITLESS_GLIDE_ATTENTION` or config `glide_attention`), then from Sleep mode and unlocks. Wind-down comes from an event, never from an evening hour ([docs/glide-wind-down-event.md](docs/glide-wind-down-event.md)).
- `limitless/jobs.py`: event-triggered job specs (wake brief, back from nap, the bedtime question, the habit check-in); `should_fire()` returns deliver, hold, drop or not_triggered with a reason through the decision window and the send gate, and `to_schedule_card()` gives the plain words a Hermes Schedule card could show. Pure functions: nothing sends by itself.
- `limitless/jobs_runner.py` + `bin/limitless-jobs [--send]`: one pass over the jobs, one line per job; dry run unless `--send`, which goes through `kevin-push` (strict) and logs a send only on real Telegram delivery. Poll it with a systemd timer: [docs/limitless-jobs-systemd.md](docs/limitless-jobs-systemd.md).
- Habit check-in gate: the check-in only goes out while a habit week is started (`habit.json` names a habit and its `week_of` is days one to seven); with no started week or after day seven it drops with "no habit week started" or "habit week over" and nothing is sent.
- `limitless/habit_start.py` + `bin/limitless-habit-start "<habit>" [--write]` (or `limitless_habit` with `start` and `confirm: true`, only after the person said yes): start that week, one habit a week; it refuses while a week is running, keeps a finished week as `habit-<week_of>.json`, and is a dry run unless `--write` / `confirm` (exit 3 when refused).
- `limitless/prediction.py` (or `limitless_habit` with `predict` / `receipt` and `confirm: true`, only after the person said yes): locks one prediction per habit week before its check-ins and, after day seven, appends one receipt (supports, contradicts or inconclusive; fewer than three logged days is inconclusive) to `predictions.jsonl` in the state dir, append-only and never rewritten.
- `limitless/wake_proxy.py`: when Sleep mode is not used, a fallback `wake` event from phone screen events (the first unlock or touch after a quiet gap of a few hours; notifications ignored); `jobs.merged_events()` lets a Sleep-mode wake win in the same gap and adds the habit cue one hour after each wake.
- One message per event: `kevin-push --once <job>:<event time>` (or `KEVIN_PUSH_ONCE`) lets only the first delivery per event key through for 12 h, whatever its words; `limitless-jobs --send` passes it on every send, and only a real delivery claims the key.
- Job owners: `limitless-jobs --send` sends the wake brief by running `bin/limitless-brief send` (never a placeholder), and skips any job listed in `external_jobs` / `LIMITLESS_EXTERNAL_JOBS` because its own sender has the real content ([who sends what](docs/limitless-jobs-systemd.md#who-sends-what)).
- One wake-up brief per wake: `bin/limitless-brief send` passes the same key (`jobs_runner.event_key`, the wake event `limitless-jobs` uses), so whichever of the two senders goes first is the only brief; with no wake event it sends with no key.
- Any other sender: `KEVIN_PUSH_ONCE=$(bin/limitless-once-key <job>) kevin-push ...` passes the key `limitless-jobs` uses for that job's event; with no event it prints nothing (exit 3) and the sender sends as before ([docs](docs/limitless-jobs-systemd.md#older-senders)).
- One MIQ prompt per night: the MIQ key is `miq:<night date>` (an event after midnight keeps the previous date until the next wake), and a sender with its own wind-down cue uses `bin/limitless-once-key miq --night`, which prints that key even with no wind-down event yet.
- Short nights: on a day with no quiet gap of 4 h, the first quiet gap of 3 h or more is one wake (`"short": true`, lower confidence, at most one per day), and a wake once seen never moves as later polls add rows; runner verdicts from a screen wake say it is a proxy, not a sleep measure.
- `limitless/aw_reader.py`: the same wake proxy also reads unlocks and app-in-foreground starts from an ActivityWatch-for-Android SQLite copy, opened read-only; set its path with `LIMITLESS_AW_DB` or config key `aw_db` (none by default).
- `limitless/feeds_evidence.py`: a hint for the habit check-in: whether the phone saw one of your feed apps (`LIMITLESS_FEED_APPS`, comma list, or config list `feed_apps`; none by default, so the hint is unknown) opened in the first hour after the wake. The check-in gains one line ("Phone: a feed app was opened in that hour" or "Phone: no feed app seen in that hour", nothing when the phone data does not cover the hour) and `limitless_habit` adds `phone_hint` (seen, not seen or unknown; a proxy); Done, No or Skip stays your tap.
- Week review (`week_review`): on the first habit cue from day seven of a started week, one message per week (key `week_review:<week_of>`): the habit, "N of M logged days" (skipped and unlogged days stay out of M; none logged says so, never "failed") and "Reply Keep or Drop."; the first Keep or Drop reply (`habit_replies.decide`, via `bin/limitless-habit-ingest`, dry run unless `--write`) writes `decision` and `decided_at` to `habit.json`, closes the week ("habit week closed") and shows in `limitless_habit`; no reply stays undecided, never a Drop.
- `limitless/habit_replies.py` + `bin/limitless-habit-ingest [--db PATH] [--write]`: closes the habit loop. The first Done, No or Skip the person sends on Telegram after the latest check-in (before it expires) goes into `habit.json` for that day, read from the Hermes session DB opened read-only (`--db`, `LIMITLESS_HERMES_DB` or config key `hermes_db`, none by default); anything else stays unlogged, an existing answer is never overwritten, and it is a dry run unless `--write`.
- `limitless/owner_messages.py`: when the person last wrote to any agent, across every machine's Hermes session DB (`LIMITLESS_OWNER_DBS`, os.pathsep-separated, or config list `owner_dbs`; none by default), read-only and timestamps only; `limitless_state` and the card show it as `messages: wrote recently`, `quiet for a while` or `no data`.
- `bin/limitless-scorecard [path]`: print the weekly review's "North star (self-reported)" block (criterion names without their parenthetical thresholds); read-only, prints nothing when there is no table.
- `scripts/replay_log.py`: replay a delivery log through the gate, read-only, counts only.

## Tools and hook
The repo root is a Hermes directory plugin (`plugin.yaml` + `__init__.py` with `register(ctx)`); all logic is in `limitless/`, which imports and tests without Hermes. Install by placing the repo at `~/.hermes/plugins/limitless/` and adding `limitless` to `plugins.enabled`.

Every tool returns an evidence envelope: `{value, modality, age_h, evidence_tier}`, where modality is `measured`, `imported`, `proxy`, `self_report` or `messages` (message timestamps). Missing data is `value: null` with a `reason`, never a guess.

| Tool | Returns |
|---|---|
| `limitless_status` | each input's age, the inputs that are not recording (over 24 h old or down), the last pipeline run |
| `limitless_state` | today's card and its parts (window, sleep, readiness, habit) as coarse labels |
| `limitless_window` | `peak`, `trough`, `anytime`, `asleep` or `unknown`, from Sleep mode, the wake event and the last unlock, never the clock. Bands are hours since wake (config `window_bands`) |
| `limitless_habit` | this week's one habit and its check-ins: Done, No, Skipped; a day with no answer is unlogged, not No |
| `limitless_scorecard` | the weekly review's north-star block: at most 5 plain lines (green/amber/red counts, "all green for W of 4 weeks" or "not all green yet", the three criteria furthest from green) from the hand-kept scorecard table at `LIMITLESS_SCORECARD` or config `scorecard`; counts only, no evidence text |
| `limitless_capture` | appends one line to `captures.jsonl`; it records only and never starts work |

The `pre_llm_call` hook adds a state card of at most 6 lines to each turn. It is cached until the window class or a state file changes. Privacy tier T2 is the default: coarse labels only ("sleep short (proxy)", "readiness low (imported)") and every digit masked. Set `LIMITLESS_RAW_IN_PROMPT=1` to opt in to raw numbers. The state dir is `LIMITLESS_STATE`, else `"state"` in `LIMITLESS_CONFIG` (`~/.config/limitless/config.json`); it is read-only except for captures. Its file shapes are in `limitless/state_reader.py`, with synthetic examples in `tests/fixtures/state/`.

Privacy tiers: T0 = raw values never enter a prompt; T1 = coarse labels made at the source by code (`limitless/labeler.py`) or, optionally, a small local CPU-only model (`LIMITLESS_T1_CMD` or config `t1_model_cmd`, none by default; any error or out-of-set answer falls back to the rule label); T2 = a cloud model sees T1 labels only.

Roadmap: event-triggered jobs for the wake brief, the post-nap message and the bedtime question, offered as Hermes [Schedule cards](https://github.com/NousResearch/hermes-agent/pull/158289) and gated by decision windows. Then a weekly review and N-of-1 experiments. Data comes from adapters for [NOOP](https://github.com/kvnloo/noop) (WHOOP/Oura), Health Connect, smart-scale fusion, a REHIT bike app, ActivityWatch and Anki.

## Tests
```bash
python3 -I -m unittest discover -s tests
```

## License
MIT
