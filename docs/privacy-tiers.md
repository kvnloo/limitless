# Privacy tiers

Health data reaches a cloud model only as coarse labels, unless the person opts in for that request.

| Tier | What | Where it is made |
|---|---|---|
| T0 | raw numbers (hours slept, a readiness value) | the state dir; never in a prompt without the opt-in |
| T1 | coarse labels ("sleep short", "readiness low", "fresh") | code (`limitless/labeler.py`) or an optional local model |
| T2 | what a cloud model sees: T1 labels only | the `pre_llm_call` state card and the tool results |

Another plugin's or an MCP server's health tool is kept at T1 by the result tier filter: every number in a tool result listed in config `t0_tools` becomes words before it enters context ([result-tier.md](result-tier.md)).

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

## Local model labeler

The T1 label can come from a small local model instead of the rules, through `LocalModelLabeler`
(`limitless/labeler.py`). It is off by default. `LIMITLESS_T1_CMD`, else config `t1_model_cmd`, names a command
that reads one fixed prompt on stdin (the kind and its allowed words) and prints one allowed word. Only a value
the rules can label is sent; a missing or unknown value never is.

`bin/limitless-t1-local` is that command for a llama.cpp-style CLI (`llama-cli`, or a build that takes the same
flags). It is stdlib only. It runs the CLI once and prints the first allowed word, from the prompt's own list,
that appears in what the model said. Anything else prints nothing and exits 1.

| Key | What |
|---|---|
| `t1_model_cmd` (env `LIMITLESS_T1_CMD`) | the command the labeler runs: the runner, or any CLI that meets the contract |
| `t1_bin` (env `LIMITLESS_T1_BIN`) | the llama.cpp CLI binary; no default path |
| `t1_model` (env `LIMITLESS_T1_MODEL`) | the GGUF model file; no default path |
| `t1_threads` | CPU threads (`-t`), default two |
| `t1_timeout_s` | the runner's wall-clock limit in seconds; it can only lower the default, which stays below the labeler's own |

A synthetic config (made-up paths and model name):

```json
{
  "t1_model_cmd": "/opt/limitless/bin/limitless-t1-local",
  "t1_bin": "/opt/llama/llama-cli",
  "t1_model": "/opt/models/tiny-model.gguf",
  "t1_threads": 2
}
```

The model must run on the CPU. The runner passes `-ngl 0` (no layer offloaded to a GPU), gives the CLI
`CUDA_VISIBLE_DEVICES` and `HIP_VISIBLE_DEVICES` set to empty, and refuses to start when either is non-empty. It
asks for a few tokens at most, greedy (`--temp 0`, `--top-k 1`), with the prompt not shown back
(`--no-display-prompt`) and no conversation mode (`-no-cnv`). On a timeout it kills the CLI's whole process
group, so nothing outlives the labeler.

The rule label wins on any doubt: no allowed word, a digit anywhere in the model's output, a non-zero exit, a
timeout, a missing binary or model file, or a prompt without an allowed list all give the rule label. When the
model names two allowed words, the first one wins. The runner never echoes the prompt, never prints a digit,
never writes a file and never downloads a model.

The doctor's `local labeler` row says off, set or broken in words. It only checks that the command, the binary
and the model file exist, and its tool rows use the rule labels, so a report never runs the model
([doctor.md](doctor.md)).

The real output of `python3 -I scripts/t1_local_example.py`, with a fake CLI that prints canned text and an
empty `tiny-model.gguf` (no model runs):

```text
rule label for sleep_h 5.3: short
the model says an allowed word: local label: ok
the model says no allowed word: local label: short (the rule label)
the model says a digit: local label: short (the rule label)
the model runs past the timeout: local label: short (the rule label)
local labeler: live: set: not checked yet (no check file is set, so none is required); the command, the model binary and the model file exist (the model is not run here)
local labeler: missing: broken: the model binary or the model file does not exist; the rule labels are used
```

## Local model check

Before the labeler uses a local model, `bin/limitless-t1-check` shows whether that model agrees with the rule
labels. It is stdlib only and runs only when you call it: the doctor, the tools and the labeler never run it.

It sends a fixed set of synthetic labeler prompts. Each one is built from the labeler's own prompt and one
kind's allowed words, with a made-up value shipped in the code (`limitless/t1_agreement.py`), and it reads no
state. Every kind with a rule is covered, and so is every word a present value can get. Each prompt goes once
through the labeler's own call path (`LocalModelLabeler.answer`: the same timeout, the same parsing, no GPU). The
answer is compared with the rule label for that value. A digit, a word outside the set, a non-zero exit or a
timeout (the model is killed) counts as no answer.

It prints words only, never a digit:

- `agrees on all checks`, `agrees on most checks` (more than half) or `agrees on few checks`;
- `unknown: <reason>`: no local model command set, the command line cannot be read, its program does not
  exist (in these three cases nothing runs), or every call failed;
- one line per kind: `agrees` (every check), `disagrees` (any check got another allowed word) or `no answer`.

`--json` gives the counts behind the words, for tests and scripts. The exit status is zero only when the
result meets the minimum. This is not a capability score. It only says whether the model gives the same
coarse words as the rules on these inputs.

| Key | What |
|---|---|
| `t1_check_file` | a file name inside the state dir. When it is set, the check writes its verdict words there (one line, mode 0600, replacing the last one) and the labeler uses the model only while that saved result meets the minimum. An absolute path or one that leaves the state dir counts as no check on file. Unset (the default): nothing is saved and the labeler works as before |
| `t1_min_agreement` | `all`, `most` (the default) or `few`. An unknown result never passes |

The doctor's `local labeler` row reads the saved words and never runs the model. It says
`set: checked, agrees on most checks` or `set: not checked yet`. With `t1_check_file` set and no passing check
on file, the row is off and the rule labels are used. A new model needs a new check: the saved words do not
name the model.

The real output of `python3 -I scripts/t1_check_example.py`. A fake model script stands in for the model and
no model runs. The fake is wrong on one kind in the first run and wrong everywhere in the second. The third run
has no command set:

```text
# before any check, with t1_check_file set:
local labeler: off: set: not checked yet, so the rule labels are used until a passing check is on file; the command exists; it is not the bundled runner, so no model file is checked (the model is not run here)
the labeler uses the model: no
$ limitless-t1-check   # a fake model that is wrong on one kind
local model check: agrees on most checks
sleep_h: agrees
readiness: agrees
age_h: agrees
owner_message_age_h: disagrees
saved for the labeler
meets the minimum agreement (most): yes
exit status: zero
local labeler: live: set: checked, agrees on most checks; the command exists; it is not the bundled runner, so no model file is checked (the model is not run here)
the labeler uses the model: yes
$ limitless-t1-check   # a fake model that always says a wrong allowed word
local model check: agrees on few checks
sleep_h: disagrees
readiness: disagrees
age_h: disagrees
owner_message_age_h: disagrees
saved for the labeler
meets the minimum agreement (most): no
exit status: one
local labeler: off: set: checked, agrees on few checks, below the minimum, so the rule labels are used; the command exists; it is not the bundled runner, so no model file is checked (the model is not run here)
the labeler uses the model: no
$ limitless-t1-check   # no model command set
local model check: unknown: no local model command set
saved for the labeler
meets the minimum agreement (most): no
exit status: one
local labeler: off: no local model command set, so the rule labels are used
the labeler uses the model: no
```
