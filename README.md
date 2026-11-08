# Continuity Guard

**Catches story contradictions in a new episode of a long-running series before anyone pays to generate the video.**

Live demo: https://continuity-guard-jayfsorwdlqkyptzz8kmsp.streamlit.app/

Give it episodes 1 to N and a new episode. It flags every line that breaks the story so far: a dead character who speaks, an age that changes, a cousin who becomes a brother, someone using a secret they never learned, an injury that vanishes. Each flag quotes **both lines word for word**, with episode and timestamp, so an editor can verify it in seconds.

```text
NEW     ep 3 00:08: ROSE: Get out of my house, Victor.
EARLIER ep 2 00:40: The heart monitor flatlines. The doctor covers Rose's face with the sheet.
WHY     Rose died in episode 2 and speaks here with no flashback, dream or revival.
```

---

## 1. The problem

Microdramas and other serialized shows run for hundreds of short episodes, and more of them are now written with AI help or by several writers in turn. Whoever writes episode 80, a person or a model, usually works from a series bible and the last few episodes, not from all 79 before it. Small contradictions slip in:

- a character who died comes back with no explanation
- an age, job or eye colour changes between episodes
- a cousin becomes a brother, or an ex-wife becomes a sister-in-law
- someone acts on a secret they were never told
- a broken arm is fine two scenes later

Each one breaks the audience's trust. In an AI video pipeline each one is also expensive: by the time someone notices, the episode has already been generated and has to be paid for again.

Catching these by hand means rereading the whole series for every new episode, which doesn't scale. Giving the whole series to a language model doesn't work well either. Hundreds of episodes overflow or dilute the context, the model struggles to tell a mistake from an intended twist (a flashback, a lie, a dream, a faked death), and an answer with no evidence is hard for an editor to trust.

So a useful checker has to:

1. remember the story so far without rereading all of it each time
2. tell real contradictions apart from deliberate twists
3. back every flag with the exact lines that conflict, so a person can confirm it in seconds
4. cost about the same for episode 500 as for episode 5

Continuity Guard does this by keeping a ledger of grounded facts, checking each new episode against it with cheap code rules first and an AI judge second, and only reporting flags whose quotes can be found word for word in the scripts. Section 4 explains how.

---

## 2. Try it in 2 minutes (no API key)

```bash
git clone <your repo url> continuity-guard && cd continuity-guard
python -m venv venv && source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python cli.py demo          # offline run on 3 made-up episodes
python -m pytest -q         # 32 tests (on Windows use python -m for pytest and streamlit)
python -m streamlit run app.py   # the UI: press "Load demo show", then "Build story ledger"
```

`demo` uses the **offline baseline** (regex extraction, no AI), so it runs anywhere. It finds the three rule-based errors planted in episode 3 of the demo show. The fourth one, an injury that vanishes, needs the AI path. The answers are in `tests/fixtures/DEMO_ANSWERS.md`.

---

## 3. Step by step on a full series

### Step 1: install the full version and add a free API key

```bash
pip install -r requirements-full.txt   # adds sentence-transformers + LanceDB
cp .env.example .env                   # paste GOOGLE_API_KEY (Google AI Studio) or GROQ_API_KEY
```

The provider and model are set in `config.yaml`. The default is `google_genai` / `gemini-3.5-flash-lite`. Check Google AI Studio for the current free models and limits, and set `rpm_limit` to stay under them.

### Step 2: get episodes, either your own scripts or a generated series

**A. You have scripts:** put them in `data/raw/` and parse them.

```bash
python cli.py parse --input data/raw --show show1
```

**B. You have no scripts:** generate an original series the way an AI writing pipeline would. The writer model sees the series bible plus summaries of only the last `--memory` episodes, and is never told to make mistakes. Any contradictions it introduces are natural AI-writer drift, which is exactly what this tool is for. Then plant errors on top of it in Step 6 to measure recall.

```bash
python tools/generate_series.py --show gen1 --episodes 30 --memory 3      # about 60 calls, ~8 min at rpm_limit 8
python cli.py parse --input data/generated/gen1 --show gen1
```

Use `--show gen1` in every step below. Edit `tools/premise_example.yaml` to change the story. The generated series is original content, so `data/generated/` is **not** gitignored and can go in the repo as sample input.

For a fairer test, write with one model and check with another, so the checker doesn't share the writer's blind spots: `python tools/generate_series.py --provider groq --model <name> ...`, then check with Gemini.

Optional experiment: generate a second series with `--memory 1`, build both, and compare flags per episode in each `outputs/<show>/summary.json`. If less memory means more drift, that shows the writer's limited memory is what causes the contradictions.

**After A or B:**

Read the output. Every episode should show scenes, lines, dialogue and zero lines without a timestamp. **If you see warnings**, your scripts' layout differs from what `guard/parse.py` expects. Open one episode, compare it with the patterns at the top of `parse.py` (`LEAD_TS`, `DIALOGUE`, `SCENE_HEAD`), adjust, and rerun. This is the only file that depends on the input format. Check one result by eye: `data/processed/show1/ep_01.json`.

### Step 3: check the characters (human in the loop)

```bash
python cli.py characters --show show1
```

The AI groups name variants ("ETHAN", "Ethan Sterling", "Mr. Sterling"). Open `store/show1/characters.yaml`, fix wrong merges, add missed aliases. It takes about 5 minutes once per show and prevents a whole class of false alarms.

### Step 4: build the story ledger

```bash
python cli.py build --show show1
```

Episodes are processed in order. Each one is checked against the episodes before it, then its facts join the ledger. Expect about 3 to 5 model calls per episode. At `rpm_limit: 8`, 50 episodes take roughly 20 to 30 minutes. Everything is cached in `cache/`, so reruns are fast and free.

Outputs, all in `outputs/show1/`:

| File | What it is |
| --- | --- |
| `reports/ep_02.json … ep_50.json` (+ `.md`) | Flags for each episode |
| `report.html` | Every flag on one page; open in a browser |
| `story_bible.md` | Every character's facts in story order, with citations |
| `summary.json` | Facts, candidates, flags and seconds per episode |
| `run_log.jsonl` | Every model call: model, tokens, seconds, cached or not |

### Step 5: label the real flags (precision)

```bash
python cli.py labels --show show1      # writes outputs/show1/labels_natural.csv
```

Open the CSV in Excel or Google Sheets and fill the `label` column for each flag with `true_error`, `intended_twist` or `false_alarm`. Save it as CSV, then run `python cli.py labels --show show1` again to print precision overall and per rule. A `true_error` found in a real series is the best evidence the tool works, so keep the clearest two or three as examples.

### Step 5b: improve, then measure again (v1 → v2)

Keep each version's results so you can compare them:

```powershell
Copy-Item outputs\show1 outputs\show1_v1 -Recurse          # snapshot before changing anything
```

Then change one thing at a time, rebuild with `python cli.py build --show show1 --fresh`, and rerun `python cli.py labels --show show1`. Labels you already gave are reused; only new flags need labelling.

- **Code fixes need no new model calls.** Extraction is cached, so a rebuild after a rule change is fast and free.
- **Prompt v2:** set `extract.prompt: extract_facts_v2` in `config.yaml`. It is stricter about deaths (a flatline, code blue, being shot or unconscious is not death) and about in-law direction. This re-extracts every episode, about 30 calls.

### Step 6: plant errors and score (recall + ablation)

```bash
python eval/seed_errors.py --show show1 --episodes 31-40 --per-type 5
# optional, more realistic: write ~10 by hand in eval/manual_seeds.json (see manual_seeds.example.json)
python eval/seed_errors.py --show show1 --episodes 31-40 --per-type 5 --manual eval/manual_seeds.json

python eval/run_eval.py --show show1                      # rules, judge and full modes
# fill the label column in outputs/show1/labels_natural.csv, then rerun for precision
python eval/run_eval.py --show show1
python eval/run_eval.py --show show1 --modes full --provider groq --model <model> --tag modelB
```

The table lands in `outputs/show1/eval/eval_results.md`: recall per error type, precision, flags per episode and seconds per episode for each setup. Missed seeds are listed in `eval_results.json` and should go into `failures.md`.

### Step 7: cost

```bash
python cli.py stats --show show1     # tokens per episode per run and stage
```

Multiply tokens per episode by your model's price per token to get the cost of checking one episode, then by your monthly episode volume to estimate cost at scale.

### Step 8: check a new episode

```bash
python cli.py check --show show1 --episode path/to/new_episode.txt          # ledger unchanged
python cli.py --provider ollama --model qwen2.5:7b check --show show1 --episode path/to/new_episode.txt
```

Or use the **Check episode** tab in the app, and switch the model in the sidebar. `--commit` adds the new episode to the story after checking.

---

## 4. How it works

```text
episode script -> parse.py (code) -> extract.py (AI) -> grounding.py (code) -> rules.py + similar past facts (code)
               -> judge.py (AI) -> verify pass (AI) -> report.py (code, re-checks both quotes) -> editor (human)
characters.yaml (human) feeds extract;  ledger.py (code: JSON + LanceDB) feeds rules;  episode k joins the ledger after its check
```

| Step | AI, code or human | Why |
| --- | --- | --- |
| Parse screenplay | Code | Deterministic; ids like `E12L041` make every claim checkable |
| Extract facts | AI | Needs reading comprehension; one call per episode |
| Ground quotes | Code | Rejects any quote not found word for word: **this is how invented facts are stopped** |
| Rules | Code | Dead character active, stable attribute changed, relationship changed, secret before learned: cheap, certain, unit-tested |
| Similar past facts | Code + embeddings | Finds related earlier facts the rules don't cover (injuries, timeline) |
| Judge | AI | Contradiction vs development (twist) vs consistent; batched per episode |
| Verify | AI | A second pass that tries to argue each flag away (flashback, lie, time skip) |
| Characters, final call | Human | Fix aliases once per show; accept, reject or mark intended twist in the app |

Design rules: flagged facts join the ledger as **disputed**, so one error doesn't cause a chain of flags. Checking is **incremental**, so episode 500 costs the same as episode 5. The model is **two lines of config**.

`mode` (config or `--mode`) gives the ablation rows: `rules` = no AI judging, `judge` = AI judge, `full` = judge + verify. Provider `offline` = no AI at all.

---

## 5. Project structure

```text
continuity-guard/
├── cli.py                  parse / characters / build / check / bible / stats / demo
├── app.py                  Streamlit UI
├── config.yaml             model, thresholds, paths
├── guard/
│   ├── schemas.py          Line, Scene, Episode, Fact, Candidate, Flag
│   ├── parse.py            raw scripts -> Episode JSON (txt, md, fountain, docx, pdf, json)
│   ├── llm.py              model factory, JSON parsing + repair, cache, retry, rate limit, token log
│   ├── offline.py          regex baseline (no AI): tests, demo, ablation
│   ├── extract.py          episode -> facts
│   ├── grounding.py        quote verification
│   ├── characters.py       alias resolution
│   ├── embed.py            sentence-transformers or hashing embeddings
│   ├── ledger.py           story so far: ledger.json + vectors + LanceDB
│   ├── rules.py            deterministic checks
│   ├── judge.py            AI judge + verify, final grounding
│   ├── pipeline.py         build / check
│   ├── report.py           JSON, Markdown, HTML
│   └── bible.py            story bible
├── prompts/                extract_facts, judge_conflict, verify_flag, resolve_aliases
├── eval/                   seed_errors.py, run_eval.py, manual_seeds.example.json
├── tools/                  generate_series.py + premise_example.yaml (test series when you have no scripts)
├── tests/                  32 tests + a made-up demo show
├── failures.md             known failure cases
└── ai_log.md               AI tools used and where they got it wrong
```

`data/` (except `data/generated/`), `store/`, `outputs/` and `cache/` are gitignored, so **scripts you don't own and everything derived from them stay off GitHub.** Share outputs privately if you need to.

---

## 6. Deploy the app (Streamlit Community Cloud, free)

1. Push the repo to GitHub (check `git status` first: no `data/raw/`, `outputs/` or `.env`).
2. On share.streamlit.io, create an app from the repo with `app.py` as the entry point. It installs `requirements.txt` (the light version, no PyTorch).
3. In the app's **Secrets**, add `GOOGLE_API_KEY = "..."` (or `GROQ_API_KEY`). Streamlit exposes root-level secrets as environment variables, which the model layer reads. Visitors can also paste their own key in the sidebar; it stays in their session.
4. Open the app in an incognito window, press **Load demo show**, then **Build story ledger**.

---

## 7. Troubleshooting

| Symptom | Fix |
| --- | --- |
| Parse warnings: no dialogue or no timestamps | Adjust the patterns at the top of `guard/parse.py` to your scripts' layout |
| `429`, quota or `RESOURCE_EXHAUSTED` | Lower `llm.rpm_limit`; the client already retries with backoff |
| Lots of `extract_rejected` in report stats | The model is quoting loosely; try a stronger model, or read `run_log.jsonl` and the cached replies in `cache/` |
| Too many false alarms | Raise `check.min_confidence`, use `mode: full`, fix aliases in `characters.yaml` |
| LanceDB error | Set `vector_store: numpy`; it's exact and fast at one-show scale |
| Want fresh model replies | The cache is keyed on provider + model + full prompt, so edits to prompts or models are picked up automatically; delete `cache/` to force new calls anyway |

Note: on most free tiers, providers may use your prompts to improve their models. Only send scripts you're allowed to share with a third party, and keep unreleased scripts off public sites.
