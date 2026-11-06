# Evaluation

Three numbers, all measured:

1. **Recall on planted errors.** `seed_errors.py` copies target episodes and inserts lines that contradict real earlier facts from the ledger, writing `answer_key.json`. A seed counts as caught when a flag points at its exact line (or an adjacent line with the same error type).
2. **Precision on the real pack.** `run_eval.py` also checks the same episodes unseeded and writes every flag to `labels_natural.csv`. You fill `label` with `true_error`, `intended_twist` or `false_alarm`. A label is keyed by episode + line + rule, so it's reused across modes and models.
3. **Cost.** Seconds per episode from the run, tokens from `run_log.jsonl` (`python cli.py stats`).

Run with `--modes rules,judge,full` for the ablation and `--tag modelB` with a different `LLM_MODEL` to compare models. Results accumulate in `outputs/<show>/eval/eval_results.json` and `.md`.

Planted errors are cleaner than real ones, so treat recall here as a ceiling, and say so in the doc.
