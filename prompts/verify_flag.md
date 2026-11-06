A first reviewer flagged a continuity error in a microdrama series. Your job is to try to prove them wrong.

Earlier line(s), each with up to 2 lines of context:
{prior_context}

New line (episode {episode}), with up to 2 lines of context:
{new_context}

Claimed problem: {explanation}

Consider the innocent explanations: flashback, dream, imagination, a lie or a bluff, a twin, a time skip, a different character with a similar name, an off-screen event that the dialogue mentions, a reveal that the earlier line was false.
If one of them is supported by the text shown above, set "keep" to false. If none is supported by the text, set "keep" to true.
Do not invent context that is not in the lines shown.

Return ONLY JSON:
{"keep": true, "reason": "one sentence", "quotes_checked": ["exact words you relied on"]}
