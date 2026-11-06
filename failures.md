# Where Continuity Guard fails

Keep this honest and specific. The best 3 to 5 bullets go into the solution doc.

## Known by design

- **Twists vs errors depends on the model.** A hidden identity, an exposed lie or a faked death looks like a contradiction. The judge prompt and the verify pass are told to treat on-screen reveals as development, but a weak model (for example a 7B local model) will still flag some twists. The offline baseline cannot tell them apart at all.
- **Implied facts need the AI.** "Lily lifts a box with both arms" a day after her arm went into a cast is only caught by the AI path. The regex baseline misses it (see the Physical column in the eval table).
- **One flag per dead character per scene.** A dead character who speaks five times in one scene produces one flag, not five. Intended: less noise.
- **Name aliases.** "Mr. Sterling" could be Ethan or his father. A wrong merge in `characters.yaml` makes the ledger mix two people. The editor fixes this file once per show.
- **Timeline arithmetic is weak.** "Three days later" against "a week has passed" is only caught if the judge sees both lines together. Nothing adds up dates in code.
- **Errors in episode 1 can't be found.** The first episode has no earlier canon to contradict.
- **The hashing embedder only sees word overlap.** Without sentence-transformers installed, related facts phrased differently ("broken arm" vs "her arm in a cast") may not be retrieved. Install `requirements-full.txt` for real runs.

- **Generated test data has limits.** With no input pack, the test series is written by an AI model from an original premise. It drifts like an AI-written show, but its error mix may differ from Kuku's real pipeline. If the same model writes and checks, they can share blind spots; use different models for each.

## Found on the real pack

Fill this in as you label flags in `outputs/<show>/labels_natural.csv`.

| Flag | What the tool said | What was really going on | Why it happened |
| --- | --- | --- | --- |
| 21 of 28 flags in gen1 v1 (eps 13–29) | Cole is dead since ep 12 but keeps speaking and acting | Ep 12 ends on a flatline / code blue cliffhanger; CPR saves him in ep 13 | Extraction read "heart monitor flatlines" as `alive = false`; the judge (same small model) agreed every time; one wrong fact flagged every later scene with Cole. Fixed by (a) disputing a fact once two later episodes contradict it, (b) prompt v2: a flatline, code blue or being shot is not death |
| E13L010 | Cole acts after death | The line was about "Cole's loyal mechanic assistant" | The subject detector matched the possessive "Cole's". Fixed |
| E16L010 (2 rows) | Harper's age changes 24 → 32 | **Real error**: the writer gave Harper Cole's age | The same line was flagged twice with different earlier lines. Now merged into one flag |
| E06L012 | Relationship reversed | Both lines say Diane calls Evelyn "mother-in-law" | In-law direction confusion in extraction; prompt v2 spells out the direction |
| E24L013 | Harper dead after being shot | She was wounded, not killed | Same "injury read as death" problem as Cole |
