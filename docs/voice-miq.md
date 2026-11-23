# Voice MIQ

The MIQ ("Do you know the one thing that matters most tomorrow?") goes out once per night in the wind-down
push and asks for a one-tap Yes / No / Later. Typed answers rarely come back. This adds a second way to
answer it: by voice, in a z0live call. The call brief asks the MIQ, and the next `limitless-jobs` pass reads
the call's transcript and saves the person's spoken answer through the same capture store as every other
capture (`captures.jsonl`, kind `miq_answer`, source `z0live`). It is off by default.

## The z0live shape it reads

z0live documents one transcript shape: the session events. A client posts them to `POST /v1/events` and the
broker appends them to `sessions/SESSION_ID.jsonl` under its data dir, one JSON object per line
(z0live `docs/API.md`, section `POST /v1/events`, and `desktop/z0live_desktop/core.py` `export_events`, which
adds the row `id`; read at z0live commit cf52d56):

```json
{"id": 7, "session_id": "s-example", "ts": 1894707060.0, "type": "assistant_transcript", "text": "...", "data": {}}
{"id": 8, "session_id": "s-example", "ts": 1894707061.0, "type": "user_transcript", "text": "...", "data": {}}
```

Only `assistant_transcript` (what the voice model said) and `user_transcript` (what the person said) are
read. A `user_transcript` with `data.final: false` is a partial and is skipped (core.py fans those out as
partials). `ts` is epoch seconds or an ISO string. Rows are taken in `id` order. A broken last line (a
crash tail z0live has not repaired yet) is skipped. hermes-z0live (read at faff5ac) exposes call status and
traces, not transcript text, so it is not a source here.

## What counts as an answer

`voice_miq.answer_from(transcript, miq)` is pure:

- The MIQ was asked when an assistant turn holds the question's words in order, ignoring case and
  punctuation. A paraphrase ("What is your main thing for tomorrow?") is not the MIQ. That keeps a guess
  out of the capture store. The cost is that a model that rewords the question gets no capture.
- The answer is the person's final turns after that ask, up to the assistant's next turn, joined with
  single spaces. Two short turns ("yes", "finish the draft review") become one answer.
- Asked twice, the latest ask that got an answer wins. Never asked, or asked with no reply: None.

## The pass

`limitless-jobs` runs `voice_miq.run` once per pass, after the NOOP export row. Config:

- `"voice_miq"`: `off` (the default: no row, nothing read), `dry_run` (says in words what it would save,
  writes nothing) or `write`. A pass that is itself a dry run (`limitless-jobs` without `--send`) is
  always a dry run.
- `"voice_miq_sessions"`: z0live's `sessions` dir (the one under its data dir). Unset: one plain reason,
  nothing read.

The MIQ is open while tonight's MIQ push is in `jobs-sent.jsonl` (job `miq`, sent at most three hours
before the pass, `jobs.MIQ_STALE_S`) and it has not been captured yet. Only rows from after that push are
read, from the newest session files. In `write` the answer goes to `capture.capture` (the one capture
store, never a second one). Then the mark `voice-miq.json` records that MIQ: `{"miq_sent_at",
"captured_at"}`, epoch seconds only, no text, mode 0600, written atomically. A second pass for the same MIQ
does nothing. The next night's MIQ is a new one. A capture that is refused (over capture's size limit)
writes no mark and says so. Every reason is words only: no digit, and never the answer's text.

## The call brief line

When `voice_miq` is on and the MIQ is open, `limitless-call-brief` ends the brief with one line, and only
that line is added:

```
Ask once: Do you know the one thing that matters most tomorrow?
```

Once the answer is captured (or the MIQ is stale, or `voice_miq` is off) the line is gone. The line has no
digit, so the brief still passes its tier gate.

## Doctor

`limitless-doctor` has one `job voice MIQ` row, just before the context packet's row. It is `off` by
config, `missing` without the sessions dir, and otherwise `live` with the mode and when the last spoken
answer was saved, in words. It reads the mark only and never a call. `job` rows are not counted by
`--strict`.

## Example

`python3 -I scripts/voice_miq_example.py` (a temporary state dir, one synthetic MIQ push, one synthetic
call; nothing real is read and nothing is sent). Its real output:

```text
$ answer_from(call, MIQ_QUESTION)
'yes finish the draft review'
$ voice_miq off
(no row)
$ voice_miq dry_run: the call brief's last line, then the pass
Ask once: Do you know the one thing that matters most tomorrow?
Voice MIQ: would capture: the MIQ was answered in a call; would capture it as an MIQ answer (dry run: nothing written)
$ voice_miq write: the pass, the capture row, the mark
Voice MIQ: captured: the MIQ was answered in a call; captured as an MIQ answer
{"at": "2030-01-15T12:00:00+00:00", "text": "yes finish the draft review", "source": "z0live", "kind": "miq_answer"}
{"miq_sent_at": 1894707000.0, "captured_at": 1894708800.0}
$ the second pass
Voice MIQ: nothing: tonight's MIQ answer is already captured
$ the doctor row
job voice MIQ: live: write mode: last spoken MIQ answer captured under an hour ago
$ the call brief now (MIQ captured): last line
habit: none set this week
```

## What it never does

It never sends, pushes or starts a process. It never writes to z0live's data dir, keeps no second store
and has no clock-time rule. The mark holds no transcript text.
