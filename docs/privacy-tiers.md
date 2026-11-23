# Privacy tiers

Health data reaches a cloud model only as coarse labels, unless the person opts in for that request.

| Tier | What | Where it is made |
|---|---|---|
| T0 | raw numbers (hours slept, a readiness value) | the state dir; never in a prompt without the opt-in |
| T1 | coarse labels ("sleep short", "readiness low", "fresh") | code (`limitless/labeler.py`) or an optional local model |
| T2 | what a cloud model sees: T1 labels only | the `pre_llm_call` state card and the tool results |

The opt-in is `LIMITLESS_RAW_IN_PROMPT=1`. Without it the card masks every digit, and labels never hold one.

## Tier audit

`limitless/tier_audit.py` records every injection, so the tiers can be checked afterwards instead of taken
on trust. Each `pre_llm_call` card and each tool result that carries a T1 label writes one JSON line:

    {"at", "hook", "tier", "lines", "digits", "opt_in", "sha256", "blocked"}

- `tier` is `T1` when the injected text has no digit and `T0` when it has one.
- A digit without the opt-in is a bug: the card (or the digit-bearing label) is dropped, not sent, and the
  line says `"blocked": true`. This guard holds even while the audit log is off.
- `sha256` is of the injected text (for a tool result, its label words joined by newlines). The text itself
  is never written: the log holds counts and a hash only.
- The log is `$LIMITLESS_AUDIT`, else config `audit_path`; with neither set, nothing is written. The file is
  created with mode 0600 and only appended to. A failed write never breaks a turn.

The weekly check:

    bin/limitless-tier-audit --days 7

prints how many injections were sent, how many had raw numbers under the opt-in, how many had raw numbers
without it, and how many were blocked. It exits 1 when any injection had raw numbers without the opt-in. A
missing or broken log counts zero; malformed lines are skipped. It only reads.
