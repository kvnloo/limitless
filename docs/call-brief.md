# Call brief

`bin/limitless-call-brief write [--out PATH]` writes today's state card as a small Markdown file that a live
voice agent can read when a call opens, so the call already knows the day's state without raw health data
and without the person repeating himself. It only writes a file; nothing sends.

## What is in it

A header comment with a `generated` UTC stamp, a TLDR line (the window class and the asks label), then at
most three short lines of the T2 card's coarse labels. Synthetic example (fixture state):

```
<!-- limitless call brief; generated: 2030-01-15T12:00:00Z -->
TLDR: peak window; asks waiting
sleep short (proxy); readiness low (imported)
habit this week: Lights down when wind-down starts; today Done
not recording: anki, bike, scale
```

- Built from `card.build(raw=False)`: labels only, every digit masked. The card's header line, its
  `messages:` recency label and its asks line are left out (the TLDR carries the asks).
- The asks label is `tools.asks_view` ("one decision ready", "decisions waiting", "nothing waiting") when a
  queue is configured (`LIMITLESS_ASKS` / `asks_path`), else "asks waiting" when the card has its asks line.
- No numbers, no card ids (`t_...`), no message content, no ask titles. Lines are at most 100 characters.
- The body goes through `tier_audit.gate` under hook `call_brief`, never with the opt-in: a digit refuses
  the write (exit 2, nothing written, an existing brief left as it is). The stamp is outside the gated body.

## Where it goes

`--out PATH`, else config `call_brief_file` (a relative path is in the state dir). With neither it exits 0
and says "not configured". The file is written through a temp file in the same directory and a rename,
mode 0600. The directory must exist.

Idempotent: when the body is the same as the file's, the file is not touched (its mtime stays), and the
line says "call brief unchanged". So a timer can run it often. Exit codes: 0 written, unchanged, not
configured or no state dir; 1 cannot build or write; 2 refused, or bad arguments (usage on stderr).

## The reader: z0live

z0live (`voice-adapter/call_brief.py`, read at cf52d56) opens each call with a `<call_brief>` packet in the
session instructions. Its `written(chat)` reads `<chat>.md`, then `latest.md`, from its brief dir
(`HERMES_VOICE_BRIEF_DIR`) as plain text, first 4000 characters, only when the file's mtime is under three
hours old; otherwise it falls back to a digest of the chat. This brief is in that shape: plain Markdown,
one header comment, short lines.

Two things to know before pointing `call_brief_file` at that dir:

- `latest.md` is also where z0live's own `hermes-voice-brief` saves a brief the chat agent wrote. Writing
  this brief there replaces that one. A separate file name in the dir is not read by z0live today; reading
  it would be a small change in `build()` there (append it after the written brief or the digest).
- z0live's freshness is the mtime. An unchanged brief keeps its mtime (above), so after three hours with
  no state change z0live treats it as stale and uses the chat digest instead. The `generated` stamp is the
  time the content last changed, for a reader that wants its own rule.

## Timer example

Generic systemd user units; names and paths are placeholders.

```ini
# ~/.config/systemd/user/limitless-call-brief.service
[Service]
Type=oneshot
ExecStart=/path/to/limitless/bin/limitless-call-brief write

# ~/.config/systemd/user/limitless-call-brief.timer
[Timer]
OnUnitActiveSec=5min
OnBootSec=1min

[Install]
WantedBy=timers.target
```

`systemctl --user enable --now limitless-call-brief.timer`. With `call_brief_file` set in the config the
service needs no `--out`; the state dir comes from `LIMITLESS_STATE` or `"state"` in the config as usual.
