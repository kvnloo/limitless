# The learn skill, limitless:learn

The plugin's second read-only Hermes skill, [skills/learn/SKILL.md](../skills/learn/SKILL.md), tells an agent
how to run a learning turn over tools the plugin already has, in four steps and at most one per turn:

- a struggle-first guess: ask for the person's guess before any explanation;
- explain-back: they say it back in their own words (voice is fine), saved verbatim with `limitless_capture`
  and `kind: explain_back`; never graded, never scored, no follow-up;
- a notebook of unknowns: an open question is saved with `limitless_capture` and comes back in the week
  review (`limitless_ideas`);
- spaced review: a short Anki review is offered only when `limitless_window` says trough.

A decline is fine and is never logged as a miss. The skill quotes digit-free labels only (T2), and holds no
advice on what to take, no score, grade, level or streak and no clock time. It adds no tool, no job and no
write: `limitless_capture` was already the plugin's one write.

## Registration

`limitless/coach_skill.py` holds one small tuple, `NAMES = ("coach", "learn", "chief")`; each name's text is
`skills/<name>/SKILL.md`. `register(ctx)` calls `coach_skill.register(ctx)` last, after the tools, hooks
and schedule cards:

- A host whose ctx has a callable `register_skill` (Hermes: `register_skill(name, path, description="",
  frontmatter=None)`) gets one call per name, in order, each with the description from that skill's own
  frontmatter. The agent loads them as `limitless:coach` and `limitless:learn` with `skill_view`.
- A host without it (an older Hermes) gets nothing and one content-free info line in all:
  `limitless: the host has no skill registration; the plugin's skills are not registered`
- A call that raises (a bad name, a missing file, anything else) gets one content-free warning line and
  the next skill is still offered, so a refused `coach` never stops `learn` or `chief` (and the other way round):
  `limitless: the host's skill registration failed; register went on`

The tests: `tests/test_learn_skill.py` keeps the skill short, its frontmatter name `learn` (the dir name)
with a "Use when ..." description, every tool it names in `plugin.yaml` `provides_tools`, the four steps in
order, Anki only in a trough, and no clock time, dosing word or score/grade word offered as a feature. The
text checks are shared with the coach skill's tests in `tests/skill_checks.py`.
`tests/test_learn_register.py` registers against fake hosts with, without and partly refusing
`register_skill`.

## Registration test output

```text
$ python3 -I -m unittest discover -s tests -p test_learn_register.py -v
test_a_host_with_register_skill_gets_both_skills (test_learn_register.Register.test_a_host_with_register_skill_gets_both_skills) ... ok
test_a_host_without_it_gets_one_line_in_all (test_learn_register.Register.test_a_host_without_it_gets_one_line_in_all) ... ok
test_one_missing_skill_file_still_lets_the_other_register (test_learn_register.Register.test_one_missing_skill_file_still_lets_the_other_register) ... ok
test_one_raising_call_still_lets_the_other_register (test_learn_register.Register.test_one_raising_call_still_lets_the_other_register) ... ok
test_plugin_register_still_works_without_register_skill (test_learn_register.Register.test_plugin_register_still_works_without_register_skill) ... ok
test_the_skill_names_are_a_small_tuple_with_a_file_each (test_learn_register.Register.test_the_skill_names_are_a_small_tuple_with_a_file_each) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.127s

OK
```

## Against a real Hermes host

The checkout's tracked files loaded as a directory plugin (`plugins.enabled: [limitless]`) into a Hermes
install's own `PluginManager`, which has `register_skill`:

```text
plugin: {'name': 'limitless', 'enabled': True, 'tools': 30, 'hooks': 4, 'error': None}
list_plugin_skills('limitless'): ['chief', 'coach', 'learn']
find_plugin_skill('limitless:coach') -> skills/coach/SKILL.md
find_plugin_skill('limitless:learn') -> skills/learn/SKILL.md
metadata: {'name': 'limitless:coach', 'description': 'Use when coaching over limitless tools. Act only on a yes.'}
metadata: {'name': 'limitless:learn', 'description': 'Use when the person wants to learn or understand something. Offer one learning step, never a grade.'}
```
