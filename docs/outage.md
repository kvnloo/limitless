# Input outages: said once, in words

An input can go silent for days with nobody noticing: the wearable stops syncing, the phone app is killed, a
laptop sleeps. The plugin notices and says so once, in plain words, with what would help. Suggest only:
it never restarts, kills or starts any app, service or process. The person decides.

## What counts as an outage

"Live" is `limitless_status`'s rule, read through the doctor (`tools.status`, `doctor.input_rows`): an input's
age in `inputs.json` plus the snapshot's age, against the same stale threshold (`envelope.STALE_H`), or the
sync reporting it `down`. No threshold is copied. An input with no age at all is unknown, never an outage.

- An outage starts at the first poll that sees the input not live (or, when it has an age, when it last
  recorded) and ends when it is live again.
- Each outage is said at most once. When the input records again, its mark is cleared silently: there is no
  "back" message. A later outage of the same input is said again.
- A poll is a wake brief being sent (`bin/limitless-brief send`). `limitless-brief build` only previews: it
  writes no mark.

## The brief line

One line at the end of the wake brief body (`brief_post.finalize`, from `jobs_runner.brief_outage`), through
the tier audit gate (hook `brief:outage`), like the naps and flow-ledger lines:

    Not recording: wearable (since about two days ago). Open the app once to restart it.

Several inputs that stopped since the last brief share one line; "since" is the oldest of them. The hint
comes from config `outage_hints` (input name -> one short plain sentence); no hint set means no hint text, and
a hint with a digit is dropped, never rewritten. The line is digit-free (`doctor.age_words`, `doctor.words`).
It has no push of its own and no job: it rides in the brief that is already going out, through the same gate
(quiet, once per wake). The outage is marked told only after that brief was really delivered, so a dropped or
failed send says it at the next brief instead.

## Config

| key | default | meaning |
| --- | --- | --- |
| `input_outage` | on | `false` (or `"off"`): no line and no mark write; the tool says off |
| `outage_ignore` | none | input names never reported (some inputs are expected to be stale for weeks) |
| `outage_hints` | none | input name -> one short sentence, such as "Open the app once to restart it." |

## The mark file

`outage.json` in the state dir, written atomically with mode 0600, holds input names and epoch seconds only:
`{"since": {name: t}, "told": {name: t}}`. No hint, no age, no other text.

## The tool

`limitless_outages` lists every current outage, told or not, minus `outage_ignore`: "not recording: wearable
(since about three days ago) and phone (since just now)" or "every input is recording", with `inputs` the
names in words. Modality derived, digit-free label. Read-only: nothing is written, marked or sent. The doctor
reports it off when `input_outage` is false.

No clock time is used anywhere: every age is counted from the inputs snapshot and the poll.

## Example

Synthetic snapshots, one wake brief a day, `scale` in `outage_ignore`
(`python3 -I scripts/outage_example.py`, real output):

```text
day one: everything records
  brief line: (none)
  limitless_outages: every input is recording
  outage.json keys: since=[] told=[]
day two: the wearable went quiet
  brief line: Not recording: wearable (since about a day ago). Open the wearable's app once so it syncs again.
  limitless_outages: not recording: wearable (since about a day ago)
  outage.json keys: since=['wearable'] told=['wearable']
day three: still quiet, already said
  brief line: (none)
  limitless_outages: not recording: wearable (since about two days ago)
  outage.json keys: since=['wearable'] told=['wearable']
day four: the phone sync is down too
  brief line: Not recording: phone (since just now). Open the app once to restart it.
  limitless_outages: not recording: wearable (since about three days ago) and phone (since just now)
  outage.json keys: since=['phone', 'wearable'] told=['phone', 'wearable']
day five: both record again
  brief line: (none)
  limitless_outages: every input is recording
  outage.json keys: since=[] told=[]
day six: the wearable went quiet again
  brief line: Not recording: wearable (since about a day ago). Open the wearable's app once so it syncs again.
  limitless_outages: not recording: wearable (since about a day ago)
  outage.json keys: since=['wearable'] told=['wearable']
off (input_outage false)
  brief line: (none)
  limitless_outages: off
```
