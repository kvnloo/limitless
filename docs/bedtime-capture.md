# Bedtime capture

Ideas that arrive near bedtime are captured, not started: the agents carry the plan overnight and the
person picks it up in the morning.

## What it does

With config `"bedtime_capture": "on"` (default off), the plugin's `post_gateway_admission` hook looks at
each admitted gateway message (after auth and slash-command dispatch). When the window from state is
`asleep` (Sleep mode on, live poll) or `wind_down` (Glide's wind-down nudge), the message is appended to
`captures.jsonl` through `capture.capture` (source `"bedtime"`), the agent turn is skipped and the reply is
one line: "Saved for tomorrow."

It passes to the agent as usual when:

- bedtime capture is off, or the window is anything else (`peak`, `trough`, `anytime`, `unknown`);
- the text is a command (`/...`) or has an urgent word (config `bedtime_urgent_words`, default
  `["urgent", "now"]`, whole words, any case);
- it is a bare habit or week answer (Done, No, Skip, Keep, Drop), which those jobs read;
- the capture is refused (empty, too long, no state dir) or anything raises: fail open, a message is
  never dropped.

The window comes from events only, never a clock time. The message text is written only to
`captures.jsonl`: it is never logged or put in the tier audit.

## The morning

`bin/limitless-brief` adds "Saved last night: N ideas" to the wake brief when the night that ended at the
latest wake (after the wake before it) holds bedtime captures. The state card gets the digit-free line
"ideas saved last night". Triage stays the person's, in a review; nothing is started or sent by capture.

## Config

```json
{"bedtime_capture": "on", "bedtime_urgent_words": ["urgent", "now"]}
```

Hook contract: Hermes `hermes_cli/plugins.py` `VALID_HOOKS` (`post_gateway_admission`) and
`gateway/run_inbound_consumer.py` `run_post_admission_hook`: the first `{"action": "handled", "reply"}`
skips the agent turn and delivers the reply on the normal route; anything else, a raise or a timeout runs
the turn.
