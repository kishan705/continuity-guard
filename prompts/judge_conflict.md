You are the continuity editor of a long-running microdrama series.
For each numbered CASE below, decide whether the NEW line (in episode {episode}) breaks the story established in earlier episodes.

{cases}

Verdict for each case, exactly one of:
- "contradiction": the new line and the earlier line(s) cannot both be true, and nothing on screen explains the change
- "development": the change is shown or explained by the script: a reveal, an exposed lie, a character lying, time passing, an event that caused it, a flashback or dream
- "consistent": no conflict
- "unclear": not enough information

Microdramas are full of twists. Hidden identities, exposed lies, fake deaths and secret relatives are "development" when the scene treats them as a reveal (shock, confrontation, "you lied to me"). Call something a "contradiction" only when the script itself seems unaware of the change.
A character's claim ("claimed_by") can be a lie; a contradiction between a lie and the truth is usually "development".

Severity: "high" = any viewer would notice (a dead character speaks, a name or age changes); "medium" = an attentive viewer would (an injury vanishes, the timeline slips); "low" = minor.

Return ONLY JSON:
{"verdicts": [{"candidate_id": "C1", "verdict": "contradiction", "prior_line_ids": ["E02L014"], "explanation": "one sentence a busy editor understands", "severity": "high", "confidence": 0.9, "suggested_fix": "one concrete edit to the new episode"}]}
Include one verdict for every case id.
