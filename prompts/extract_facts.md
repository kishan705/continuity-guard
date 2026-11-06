You extract continuity facts from part of a microdrama screenplay (episode {episode}).
A continuity editor will use these facts later to catch contradictions between episodes.

Known characters (id: names and aliases). Use these ids for "entity":
{characters}

Screenplay lines (line_id [timestamp] SPEAKER: dialogue, or (action) description):
{lines}

Extract every fact that a later episode could contradict:
- identity: name, age, job, nationality, where someone grew up
- relationship: X is Y's wife / husband / ex / sister / brother / mother / father / son / daughter / boss / cousin / fiance / friend / enemy
- status: alive, married, pregnant, missing, in prison, in hospital, fired, engaged
- physical: injury, scar, cast, pregnancy showing, hair or appearance that matters, an important object someone has
- knowledge: who LEARNS a secret, and who ACTS ON or reveals they know a secret
- location: where a character lives or is staying (only if it matters to the story)
- timeline: explicit time markers ("three days later", "a year ago", dates, deadlines)

Use these attribute names whenever they fit:
- identity: name, age, job, nationality, hometown
- relationship: relationship_to:<other character id>   (value = the role, e.g. "sister")
  entity = the person whose role it is: "Rose Sterling, Ethan's grandmother" -> entity "rose", attribute "relationship_to:ethan", value "grandmother"
- status: alive ("true"/"false"), married_to, pregnant, missing, in_hospital, employment
- physical: injury, scar, appearance, holding:<object>
- knowledge: learns, acts_on   (value = the secret in a short plain sentence, e.g. "Maya is Ethan's wife")
- location: lives_in, stays_at
- timeline: time_marker, date, deadline

Rules:
- Use ONLY these lines. No outside knowledge, no guesses about what happens next.
- Every fact cites ONE line_id and a "quote" copied EXACTLY, word for word, from that line (at most 15 words).
- mode = "stated" for action lines (true in the story world); "claimed_by:<SPEAKER>" for anything a character says (it may be a lie).
- stability = "stable" for things that should never change (name, age, birth family, past events, death); otherwise "changeable".
- One fact per attribute per line. Skip greetings, emotions and small talk.
- If nothing continuity-relevant happens, return {"facts": []}.

Return ONLY JSON in this shape:
{"facts": [{"line_id": "E01L002", "entity": "maya", "fact_type": "identity", "attribute": "age", "value": "26", "stability": "stable", "mode": "stated", "quote": "Maya Chen, 26"}]}
