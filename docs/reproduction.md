# Reproduction

## Requirements

Python 3.10+ with its standard library. Run commands from the repository root. Installing the package is optional: `python3 -m pip install -e .`.

## Inspect the existing evidence (free, offline)

```
python3 scripts/verify.py
python3 scripts/reproduce.py
python3 -m unittest discover -s tests -q
```

`verify.py` checks 34 benchmark cases and 31 saved paired records, the exact current prompt, target isolation, history alignment, chronological selection, tool protocol, and checksums. `reproduce.py` rebuilds `results/cases.csv`, `results/metrics.json`, the results table, and the three HTML review pages. It uses no credentials and makes no network calls. HTML reviewers display escaped text and do not execute recorded commands. Their manual ratings stay in browser local storage until exported; no prior private review ratings are bundled.

## Run fixtures (free, offline)

```
python3 -m curator_bench validate --config configs/example.json
python3 -m curator_bench run --offline --output runs/demo
```

Fixture answers, probabilities, and token counts are synthetic. Use a new output directory for each run.

## Run new model inference (billable)

Provide `OPENAI_API_KEY` and `TYPESAFE_API_KEY` as environment variables using your normal secret manager or local shell. `.env.example` lists the variable names; the runner does **not** load `.env` automatically. Do not put credentials in JSON configs or commit them. The API-key environment names, endpoints, and completion settings are configurable.

Choose an OpenAI Chat Completions model accessible to your account:

```
python3 -m curator_bench run --config configs/wildchat.json --model YOUR_MODEL_ID --output runs/my-wildchat
python3 -m curator_bench run --config configs/long-context.json --model YOUR_MODEL_ID --output runs/my-long-context
python3 -m curator_bench run --config configs/tool-use.json --model YOUR_MODEL_ID --case prompt-reconstruction --case chunking-limits --output runs/my-tools
```

The saved historical model identifier is `gpt-5.6-terra`. No guarantee is made about availability to other users. Different models, alias versions, caching, or provider behavior produce different experiments; preserve the resulting manifest. Generic models can run, but the bundled cost estimator returns unavailable for unsupported pricing.

Three other tool cases fail the unchanged local byte-budget check before either branch is sent. Their original messages remain available. The tool config intentionally includes all cases by default so exclusion is explicit through `--case`; do not mistake a full-suite preflight failure for provider rejection.

## Failure handling

Default retries are zero. Requests and responses are persisted incrementally. A failed Jev call does not silently fall back to full context. Unknown usage remains unavailable rather than zero. `--resume` does not replay completed or uncertain in-flight requests; changed configs/benchmarks are rejected. Published sanitized result bundles are archival and not resumable. To continue your own run, use its original output directory and config.

## Files and measurements

Per-case records include both completion requests/responses, Jev requests/responses, per-chunk traces, selected IDs, dependency-retained IDs where applicable, usage, timing, finish reason, and errors. A multi-chunk Jev stage also contains a flattened attempts list: accounting uses that list once, not again per chunk. Whole-branch times include preparation and persistence as well as model requests. Output tokens can include provider-reported reasoning tokens. The cost snapshot is in `curator_bench/costs.py` and is not a live price feed.

`checksums.json` covers the distributed benchmark inputs, provenance JSON, manifests, and case evidence. Grading rubrics are evaluation-only; do not copy them into model input. Manual quality grading remains to be done.
