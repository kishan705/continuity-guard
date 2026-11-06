# How AI tools were used

The brief asks which tools you used and one place where they got it wrong. Keep adding to this as you work.

| Tool | What I used it for |
| --- | --- |
| Claude | Brainstorming the problem, the build guide, writing the first version of the code and tests |
| Gemini / Groq (via the app) | The extraction, judge and verify models inside the tool |
|  |  |

## Where the AI got it wrong (caught while building)

1. **The first parser read a notes file as episodes.** A Markdown file of expected answers sitting in the episode folder was parsed as episodes 2–4, and the phrase "Ep 2, 01:05" inside a sentence was read as an episode heading. The parse report's warnings ("no lines parsed") exposed it. Fix: stricter heading pattern, skip README/ANSWERS files, and fail loudly on duplicate episode numbers.
2. **The first evaluation scoring over-counted.** Planted "physical" errors (which the regex baseline cannot detect) were scored as caught because they sat next to other flagged lines and the matcher allowed ±1 line. Fix: exact line match, or an adjacent line only when the error type also matches.
3. **A regex silently ignored case.** The "my sister Lily" pattern was case-insensitive, so it captured "Lily needs" as a name. It still resolved to the right character by luck. Fix: case-insensitive only on the keyword, not on the name.

4. **The first version could cause a chain of false alarms.** The "disputed" safeguard only covered facts on a flagged *new* line. When an *earlier* fact was itself wrong, every later episode was flagged against it. The first real run (gen1) exposed this: 21 of 28 flags came from one misread line. Fix: a fact contradicted by two different later episodes is disputed.

## Where the models inside the tool got it wrong

- **gemini-3.5-flash-lite read a flatline as a death** ("Heart monitor flatlines ... code blue over Cole's bed" → `alive = false`) and, as the judge, confirmed "Cole speaks although dead" 21 times; the verify pass didn't catch it because it only saw lines around the flatline, not the CPR scene in the next episode.
- The AI-generated series also had natural errors of its own: for example Harper is called "thirty-two-year-old" in ep 16 after being 24 throughout.
- Fill in more from your runs: a twist judged as a contradiction, a hallucinated quote caught by grounding (`extract_rejected` in the report stats), a wrong alias merge.
