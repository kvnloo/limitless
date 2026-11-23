# Memory palace: one optional walk, in a trough only

The ask (LE03): a memory palace built from the person's own house lives in an external memory-palace app. The
plugin never rebuilds that app and never runs the walk: it only offers the person's own link, once, at a light
moment. The learning order stays the stock app first (Anki); a palace walk is the same kind of trough-only,
optional, one-tap offer, and there is one learning offer per trough.

## Config

- `palace_link`: a deep link or URL to the person's memory-palace app, for example `palace://example`. Unset by
  default. It rides in a line the person reads, so it is checked like the breathing link
  (`wind_down.breathing_link`, called, not copied): a scheme, `://`, printable ASCII, no space and no digit.
- `palace_label`: the words in the line, default "memory palace". A label with a digit, a line break or more
  than forty characters falls back to the default.

Unset (or a link that cannot ride in a digit-free line) is off everywhere, with the one reason "no memory
palace link set": no card line, no propose rule, and `limitless_palace` says off.

## The offer

`limitless/palace.py`. `offer(state, cfg)` is the one line

    A short memory palace walk fits now. palace://example

or None. It offers only when all of these hold:

- a trough job would deliver now (`decision_window.decide` for a `trough` job, the same call `anki.offer`
  makes): never asleep, in a focus block (Glide) or focused mode (`modes.apply`), a peak, an unknown window or
  any other window;
- pushes are not muted (`quiet.check`: quiet, quiet tonight and snoozed all hold it);
- no Anki offer is on this turn's card ("trough: a short Anki review fits now"): one learning offer per trough;
- no palace offer yet for this wake day. The day is keyed on the wake event (`explain_back.wake_at`), never a
  clock time. No wake seen is unknown: no offer.

Every flag must be a known False; an unknown never offers. The line goes on the pre_llm_call state card, on a
line of its own after the card (outside `MAX_LINES`, so the link stays whole), and the card goes through
`tier_audit.gate` as always. Once the gate lets that card through, the hook writes `palace.json` in the state
dir: `{"wake_at", "offered_at"}` (epoch seconds, mode 0600, never any text). That mark is the only write.

## Propose

`limitless_propose` gains one rule, read right after the Anki rule: a trough window, no Anki collection set and
a memory palace link set give "a short memory palace walk". With Anki set the Anki rule wins the trough. An
unknown window, Anki or palace label never triggers it; `NO_SUGGESTION` stays the default.

## Reading it

Tool `limitless_palace`, read-only: `{value: {label}, modality: "derived", age_h: null, evidence_tier}`. The
label is one of "off" (with `why`: "no memory palace link set"), "fits now" (with `line`: the offer and the
person's link) or "not now: <the reason in words>". It never marks the wake day; only the card's hook does.

## Never

No clock time; no score, streak or count of walks shown to the person; no push of its own and no job (the
line only appears on the state card, or as propose's suggestion); no write except the mark file; no digit in
any line the person reads. Suggest only: the agent asks before anything happens.

## Example

`python3 -I scripts/palace_example.py` (the repo's synthetic fixture state in a temporary dir, a fixed clock,
trough bands and the example link). Its real output:

```text
# no palace_link set: off
$ limitless_palace {}
{"age_h": null, "evidence_tier": "direct", "label": {"label": "off", "modality": "derived", "tier": "T1"}, "modality": "derived", "value": {"label": "off", "why": "no memory palace link set"}}
# palace_link set, a trough
$ limitless_palace {}
{"age_h": null, "evidence_tier": "indirect", "label": {"label": "fits now", "modality": "derived", "tier": "T1"}, "modality": "derived", "value": {"label": "fits now", "line": "A short memory palace walk fits now. palace://example"}}
$ limitless_propose {}
{"label": {"label": "a short memory palace walk", "modality": "derived", "tier": "T1"}, "rule_id": "palace-trough"}
# the first trough turn
card ends: A short memory palace walk fits now. palace://example
mark: ['offered_at', 'wake_at']
# the next turn, same wake event
card ends: asks waiting on you
$ limitless_palace {}
{"age_h": null, "evidence_tier": "indirect", "label": {"label": "not now: already offered since you woke (or it is not clear when you woke), so not again until the next wake", "modality": "derived", "tier": "T1"}, "modality": "derived", "value": {"label": "not now: already offered since you woke (or it is not clear when you woke), so not again until the next wake"}}
# a peak (the fixture's own bands)
$ limitless_palace {}
{"age_h": null, "evidence_tier": "indirect", "label": {"label": "not now: your focus is high right now, so this waits for a lighter moment", "modality": "derived", "tier": "T1"}, "modality": "derived", "value": {"label": "not now: your focus is high right now, so this waits for a lighter moment"}}
# an Anki collection set too: the Anki offer wins the trough
$ limitless_palace {}
{"age_h": null, "evidence_tier": "indirect", "label": {"label": "not now: an Anki review was offered in this trough, and one learning offer per trough is enough", "modality": "derived", "tier": "T1"}, "modality": "derived", "value": {"label": "not now: an Anki review was offered in this trough, and one learning offer per trough is enough"}}
$ limitless_propose {}
{"label": {"label": "a short Anki review", "modality": "derived", "tier": "T1"}, "rule_id": "anki-trough"}
```

## Tests

`python3 -I -m unittest discover -s tests -p "test_palace_*.py" -v`, real output:

```
test_no_job_and_no_schedule_card_names_it (test_palace_card.NoPushNoJob.test_no_job_and_no_schedule_card_names_it) ... ok
test_palace_sends_nothing (test_palace_card.NoPushNoJob.test_palace_sends_nothing) ... ok
test_a_trough_adds_the_line_whole_and_digit_free (test_palace_card.OnTheCard.test_a_trough_adds_the_line_whole_and_digit_free) ... ok
test_build_without_the_offer_has_no_line (test_palace_card.OnTheCard.test_build_without_the_offer_has_no_line) ... ok
test_never_beside_the_anki_offer (test_palace_card.OnTheCard.test_never_beside_the_anki_offer) ... ok
test_never_in_a_peak_focused_mode_or_muted (test_palace_card.OnTheCard.test_never_in_a_peak_focused_mode_or_muted) ... ok
test_once_per_wake_event_and_the_mark_is_private (test_palace_card.OnTheCard.test_once_per_wake_event_and_the_mark_is_private) ... ok
test_unset_is_off (test_palace_card.OnTheCard.test_unset_is_off) ... ok
test_default_label (test_palace_config.Label.test_default_label) ... ok
test_own_label (test_palace_config.Label.test_own_label) ... ok
test_a_deep_link_or_url_is_kept (test_palace_config.Link.test_a_deep_link_or_url_is_kept) ... ok
test_a_link_that_cannot_ride_in_a_digit_free_line_is_off (test_palace_config.Link.test_a_link_that_cannot_ride_in_a_digit_free_line_is_off) ... ok
test_unset_by_default (test_palace_config.Link.test_unset_by_default) ... ok
test_unset_is_off_with_one_plain_reason_whatever_the_window (test_palace_config.Off.test_unset_is_off_with_one_plain_reason_whatever_the_window) ... ok
test_example_links_only (test_palace_docs.Docs.test_example_links_only) ... ok
test_the_doc_example_is_the_scripts_real_output (test_palace_docs.Docs.test_the_doc_example_is_the_scripts_real_output) ... ok
test_the_doc_says_what_it_never_does (test_palace_docs.Docs.test_the_doc_says_what_it_never_does) ... ok
test_the_readme_names_the_tool_the_config_and_the_doc (test_palace_docs.Docs.test_the_readme_names_the_tool_the_config_and_the_doc) ... ok
test_a_peak_or_unknown_window_never_offers (test_palace_mark.ForTurn.test_a_peak_or_unknown_window_never_offers) ... ok
test_a_trough_after_the_wake_offers_once (test_palace_mark.ForTurn.test_a_trough_after_the_wake_offers_once) ... ok
test_an_anki_offer_this_turn_means_no_palace_offer (test_palace_mark.ForTurn.test_an_anki_offer_this_turn_means_no_palace_offer) ... ok
test_every_word_is_digit_free (test_palace_mark.ForTurn.test_every_word_is_digit_free) ... ok
test_for_turn_writes_nothing (test_palace_mark.ForTurn.test_for_turn_writes_nothing) ... ok
test_muted_means_no_offer (test_palace_mark.ForTurn.test_muted_means_no_offer) ... ok
test_no_wake_seen_is_unknown_no_offer (test_palace_mark.ForTurn.test_no_wake_seen_is_unknown_no_offer) ... ok
test_unset_is_off_and_reads_nothing_else (test_palace_mark.ForTurn.test_unset_is_off_and_reads_nothing_else) ... ok
test_a_broken_mark_reads_as_none_and_a_failed_write_is_false (test_palace_mark.Mark.test_a_broken_mark_reads_as_none_and_a_failed_write_is_false) ... ok
test_mark_is_epoch_only_and_private (test_palace_mark.Mark.test_mark_is_epoch_only_and_private) ... ok
test_offered_today_is_keyed_on_the_wake_event (test_palace_mark.Mark.test_offered_today_is_keyed_on_the_wake_event) ... ok
test_own_label_rides_in_the_line (test_palace_offer.Fits.test_own_label_rides_in_the_line) ... ok
test_trough_offers_the_one_line_with_the_link (test_palace_offer.Fits.test_trough_offers_the_one_line_with_the_link) ... ok
test_at_most_once_per_wake_day_and_unknown_counts_as_offered (test_palace_offer.NotNow.test_at_most_once_per_wake_day_and_unknown_counts_as_offered) ... ok
test_never_asleep (test_palace_offer.NotNow.test_never_asleep) ... ok
test_never_in_a_focus_block_or_focused_mode (test_palace_offer.NotNow.test_never_in_a_focus_block_or_focused_mode) ... ok
test_never_muted_and_unknown_quiet_counts_as_muted (test_palace_offer.NotNow.test_never_muted_and_unknown_quiet_counts_as_muted) ... ok
test_never_outside_a_trough (test_palace_offer.NotNow.test_never_outside_a_trough) ... ok
test_not_a_dict_is_unknown (test_palace_offer.NotNow.test_not_a_dict_is_unknown) ... ok
test_off_wins_over_every_other_reason (test_palace_offer.NotNow.test_off_wins_over_every_other_reason) ... ok
test_one_learning_offer_per_trough (test_palace_offer.NotNow.test_one_learning_offer_per_trough) ... ok
test_unknown_never_offers (test_palace_offer.NotNow.test_unknown_never_offers) ... ok
test_words_reads_off_fits_now_or_not_now_with_the_reason (test_palace_offer.Words.test_words_reads_off_fits_now_or_not_now_with_the_reason) ... ok
test_a_broken_result_is_not_now (test_palace_tool.Envelope.test_a_broken_result_is_not_now) ... ok
test_fits_now_carries_the_line (test_palace_tool.Envelope.test_fits_now_carries_the_line) ... ok
test_not_now_says_why_in_words (test_palace_tool.Envelope.test_not_now_says_why_in_words) ... ok
test_off (test_palace_tool.Envelope.test_off) ... ok
test_a_peak_is_not_now_with_the_reason (test_palace_tool.ThroughThePlugin.test_a_peak_is_not_now_with_the_reason) ... ok
test_a_trough_fits_now (test_palace_tool.ThroughThePlugin.test_a_trough_fits_now) ... ok
test_an_anki_offer_is_not_now (test_palace_tool.ThroughThePlugin.test_an_anki_offer_is_not_now) ... ok
test_read_only_the_tool_never_marks (test_palace_tool.ThroughThePlugin.test_read_only_the_tool_never_marks) ... ok
test_registered_and_in_the_manifest (test_palace_tool.ThroughThePlugin.test_registered_and_in_the_manifest) ... ok
test_unset_is_off (test_palace_tool.ThroughThePlugin.test_unset_is_off) ... ok
test_words_only_no_digit (test_palace_tool.ThroughThePlugin.test_words_only_no_digit) ... ok

----------------------------------------------------------------------
Ran 52 tests in 0.352s

OK
```
