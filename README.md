# Message-Level Context Selection

Results from **31 paired cases**, comparing full conversation history against messages selected by Jev.

| Dataset | Cases | Main-model input reduction | Total cost: without → with Jev | Average time: without → with Jev |
|---|---:|---:|---:|---:|
| WildChat | 20 | 72.8% | $0.1044 → $0.1308 | 6.55s → 7.13s |
| Long context | 9 | 98.1% | $2.3124 → $0.1502 | 9.94s → 13.84s |
| Conversation with tools | 2 | 46.7% | $0.0521 → $0.0331 | 7.73s → 7.74s |

Costs are estimates summed across each dataset. With-Jev cost and time include curation. Input reduction measures main-model tokens only; Jev processes additional tokens.

**Less context did not always mean lower cost or faster answers. Answer quality has not been systematically graded.** These are small, selected samples, not evidence of improved accuracy. Three additional tool cases were blocked by the local size check; one long-context baseline answer was truncated.

[Full results](results/README.md) · [Research report](REPORT.md) · [Verify the results](docs/reproduction.md) · [Dataset sources](docs/data.md)
