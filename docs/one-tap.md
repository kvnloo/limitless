# One tap or one spoken word

Typed prompts got no answers; asks that took one tap or one spoken word did. So every message that asks the
person something ends in one plain line of two to four one-word replies, and a reply is read back whole.

- `limitless/one_tap.py`: `choices_line(options)` writes the line (`Reply: Done / No / Skip`; each option one
  word of letters, no digits, no card ids, none repeated); `parse(text, options)` reads a reply back: the whole
  message, any case, with surrounding spaces, trailing punctuation and one trailing emoji ignored, so a voice
  transcript like "done." counts. Anything else is None, never a No. `is_one_tap(body)` is the check: a body
  that asks (a `?`, a request for a reply in words, or a choices line) must end in a choices line, before the
  one `Why now` line.
- Job bodies (`jobs_runner.body`): the habit check-in ends in `Reply: Done / No / Skip`, the week review in
  `Reply: Keep / Drop`, the MIQ in `Reply: Yes / No / Later`. The habit and week replies are still logged by
  `habit_replies` (first word, as before); bedtime capture passes a bare MIQ reply to the agent instead of
  saving it as an idea.
- Asks queue (`asks.render`, `asks.reply`): each ask is its title in plain words, then a choices line from its
  own `answers` field (2-4 one-word options), default `Reply: Yes / No / Later`. A reply naming an option is
  `answered`; `Later`, or anything else, leaves the ask `waiting`, never a no. Nothing here writes the queue:
  the host still sets `delivered_at`.
- Why now (`send_gate.why_line`): every decision-window reason and a job's trigger event read as plain words
  (`decision_window.plain`), digit-free.

Nothing changes who gets a message or how often, and nothing reads a clock time.

## Why-now words

| decision_window reason | what the person reads |
| --- | --- |
| `critical: delivers whatever the window` | this is urgent, so it comes whatever you are doing |
| `asleep: holds until wake` | you are asleep, so this waits until you wake |
| `focus block running (since focus_start): holds until it ends` | you are in a focus block, so this waits until it ends |
| `anytime job and awake` | you are awake and this fits any moment |
| `window unknown: holds the peak job until a provider knows` | it is not clear yet what kind of moment this is, so this waits for a moment when your focus is high |
| `trough window open (since wake): holds the peak job` | it is a lighter moment, fine for a short read, so this waits for a moment when your focus is high |
| `peak budget spent: one decision per peak window` | you already had one decision in this focused stretch, so this one is skipped |
| `peak window open (since wake)` | your focus is high right now |
| `trough window open` | it is a lighter moment, fine for a short read |
| `wind_down window open` | it is a good moment to close the day |

Only delivered messages carry a why line, so in practice the person sees the first, fourth and last three.

## Synthetic example

A synthetic habit ("Synthetic stretch", one Done and one No this week) and two synthetic asks. Real output of
`jobs_runner.body`, `send_gate.outgoing`, `asks.render` and `asks.reply`:

```text
Did you do it today: Synthetic stretch?
Phone: no feed app seen in that hour
Reply: Done / No / Skip
Why now: it is your habit cue; you are awake and this fits any moment
---
Synthetic stretch: 1 of 2 logged days this week.
Reply: Keep / Drop
Why now: it is your habit cue; you are awake and this fits any moment
---
Your wind-down has started. Do you know the one thing that matters most tomorrow?
Overnight: a few tasks running, one queued
Reply: Yes / No / Later
Why now: your wind-down started; it is a good moment to close the day
---
Approve the synthetic draft
Reply: Approve / Deny / Later
---
Move the synthetic review to next week
Reply: Yes / No / Later
---
'approve.' {'id': 'ask-1', 'answer': 'Approve', 'action': 'answered', 'reason': 'a whole reply that names one of its choices'}
'Later 👍' {'id': 'ask-1', 'answer': 'Later', 'action': 'waiting', 'reason': 'Later: the ask stays waiting, never a no'}
'maybe tomorrow' {'id': 'ask-1', 'answer': None, 'action': 'waiting', 'reason': 'not one of its choices: the ask stays waiting'}
```

`bin/kevin-push` with a fake `hermes`, class `decision`, no `--why`:

```text
$ kevin-push x "Pick one" "Keep the synthetic loop?
Reply: Keep / Drop"
kevin-push: telegram
# what the phone got:
Keep the synthetic loop?
Reply: Keep / Drop
Why now: you are awake and this fits any moment
```
