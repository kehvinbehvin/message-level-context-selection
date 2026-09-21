# Message-Level Context Selection

An exploratory study of selecting whole conversation messages for each new request using Jev's Noul probabilities.

The main model receives either the full recorded history or a chronologically ordered subset selected by Jev. Messages are not rewritten, reordered, or summarized. Long histories are processed in chunks; recorded tool calls and their results are retained together.

**[Read the research report](REPORT.md)** · **[Recorded results](results/README.md)** · **[Reproduce and verify](docs/reproduction.md)** · **[Dataset sources](docs/data.md)**

## Evidence included

| Dataset | Cases provided | Paired live cases | Main-model input reduction |
|---|---:|---:|---:|
| Selected WildChat follow-ups | 20 | 20 | 72.8% |
| Selected LongMemEval cases | 9 | 9 | 98.1% |
| Author-authorized conversation with tool history | 5 | 2 | 46.7% |

Reductions compare summed main-model input tokens, excluding Jev tokens. Three tool-history cases were blocked by a local byte-budget check. These are small, selected, overlapping cases; answer quality is **not systematically graded**. Token reduction is not evidence of improved accuracy. Selection was more expensive overall on the WildChat set and slower on average on the long-context set. See the full tables and limitations.

## Verify without credentials

Python 3.10+; no third-party runtime dependencies.

```bash
python3 -m unittest discover -s tests -q
python3 scripts/verify.py
python3 scripts/reproduce.py
```

The final command recreates tables and local HTML reviewers from saved responses. Open `results/wildchat/review.html`, `results/long-context/review.html`, or `results/tool-use/review.html` in a browser. It does not call either model.

Try the runner with synthetic fixtures:

```bash
python3 -m curator_bench run --offline --output runs/demo
```

Live inference requires your own OpenAI and TypeSafe credentials and an accessible Chat Completions model. Historical runs requested and returned `gpt-5.6-terra`; this repository does not establish that this model identifier is available to every account. Example configs leave the main model unset. See [reproduction instructions](docs/reproduction.md).

## Method

1. Supply the history and current request as Jev's shared state.
2. Ask one Noul question for each historical message, using the [exact prompt](docs/method.md).
3. Retain messages with probability **≥ 0.5**, in their original order.
4. For tool histories, keep all members of a call/result group if any member passes.
5. Send the selected history and unchanged current request to the main model.

Only this method is implemented. The research report discloses differences between recorded runner versions. A full coding-agent harness, selective summarization, and a message graph are future work.

## Repository

- `curator_bench/`: runner, chunking, Noul selection, cost estimation, HTML reviewer.
- `configs/`: runnable templates; choose your own main model.
- `benchmarks/`: selected inputs, evaluation-only notes, provenance, blocked-case details.
- `results/`: sanitized live records, original experiment configs, answers, usage, and timings.
- `scripts/`: two offline utilities for verification and report regeneration.
- `tests/`: protocol, isolation, selection, failures, accounting, and reporting tests.

Code is MIT-licensed. Dataset material has separate attribution and rights; see [data documentation](docs/data.md). No credentials or full private session export are included.
