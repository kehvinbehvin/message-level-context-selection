# Message-Level Context Selection

**Exploratory report · September 2026 · kehvinbehvin**

## Abstract

We investigate selecting whole messages from conversation history separately for each user request. Jev assigns a Noul probability to each message using a fixed contribution-oriented question. The main model answers with either the full history or the selected subset. This release contains 31 completed paired cases across WildChat, constructed long-context conversations, and the author's tool-bearing conversation, plus three locally blocked cases. Main-model input tokens decrease substantially in the recorded runs. Costs and latency do not improve uniformly. No systematic blinded answer grading or held-out evaluation has been completed, so these observations do not establish better understanding or preserved accuracy.

## Research question

Can request-specific selection reduce the context supplied to a main model while preserving the information needed to interpret and answer the current user request?

The intended application is investigative conversation: accumulating evidence, returning to prior topics, tracking instructions, and using tool outputs. The selected tasks also include rewriting, reference resolution, and personal-memory questions. They should not be interpreted as a representative sample of research tasks or coding-agent performance.

## Method

The paired conditions share the current request, main model, instruction message, and completion settings. The baseline gets every message in the selected history window. The treatment gets messages selected by Jev with a threshold of 0.5, in chronological order. No model-generated summaries are introduced.

The [method specification](docs/method.md) contains the exact prompt, chunking budgets, tool dependency rule, and failure handling. Evaluation notes and rubric metadata are excluded from model inputs. Recorded calls are replayed as context, not executed.

Runs use non-streaming Chat Completions, a 2,048-token completion limit, and the Jev HTTP endpoint. Requested main model: `gpt-5.6-terra`. Jev was requested through `jev-latest`; response records preserve returned identifiers when supplied. There is one generation per branch, not repeated trials. Execution is sequential, with first-branch order alternating within each original run; separately started pilots restart that ordering. Pricing, caching, and actual returned usage are recorded.

## Dataset construction

- **WildChat:** 20 purposively selected follow-up cases from eight conversations, with two cases in each of ten categories. Questions are existing user messages. Future conversation turns are excluded.
- **Long context:** nine selected cases from three LongMemEval parent histories. Two retain the original benchmark question; seven use historical user-message prefixes. Neutral session/date labels were added. These constructed sessions are not a single organic conversation and may contain different personas.
- **Tool history:** five existing user questions from bounded episodes of the author's authorized conversation. Internal reasoning and system/developer messages are excluded. Tool calls/results are preserved in a replay envelope; local identifiers are redacted. Two cases fit the local size budget; three contain oversized atomic groups and were never submitted.

Case selection is nonrandom, and cases sharing a parent overlap. Source licensing, revision references, transformations, and release hashes are documented in [data provenance](docs/data.md). This release contains only the selected current-method runs; it is not a preregistered or independent evaluation. The prompt was developed through inspection of related cases, including this WildChat set.

## Results

See the [generated tables](results/README.md) and [per-case CSV](results/cases.csv). The tables are rebuilt from the saved responses; quality labels have not been assigned.

- WildChat main-model input decreased by **72.8%**, but estimated total treatment cost was **$0.1308**, compared with **$0.1044** for the baseline.
- Long-context main-model input decreased by **98.1%**. Estimated treatment cost was **$0.1502**, compared with **$2.3124** baseline; mean treatment duration was longer, **13.84s versus 9.94s**.
- The two completed tool cases reduced main-model input by **46.7%**, with estimated treatment cost **$0.0331** versus **$0.0521** baseline. The blocked cases are excluded from these numerical comparisons and remain part of the released dataset.

These reductions measure main-model input only. Jev additionally processed 137,683 input tokens on WildChat, 1,587,513 on long context, and 43,416 on the two tool cases. Input reduction therefore should not be equated with total-system token reduction. Costs use a historical list-price model, including recorded cache details, not billing invoices.

## Qualitative observations

The tool-history prompt-reconstruction case produced identical complete answers with and without selection, retaining 22 of 92 history messages. This is one compatibility and answer-equivalence observation, not a general accuracy result.

In the car-service long-context case, two useful evidence messages received probabilities of 0.46, below the threshold, and the selected history was empty. The baseline identified the GPS issue; the treatment lacked the evidence. This is a false-negative example that large token reductions alone would conceal.

One baseline long-context answer reached the output limit. Truncation is recorded in the results and should be considered during grading. Other successful API responses are not automatically correct. The chunking-design case also illustrates possible scope drift: answers proposed additional summarization and multi-pass mechanisms beyond the experiment being discussed.

## Limitations

1. Small, curated, overlapping samples with prompt development on related material; no held-out generalization claim.
2. No blinded grading, repeated generations, confidence intervals, or independently verified answer-quality aggregate.
3. Jev decisions see only their chunk. Cross-chunk references and duplicates can be missed. Probabilities have not been calibrated for this task.
4. A conservative UTF-8 byte proxy is used rather than Jev's tokenizer. Local preflight rejection is not evidence of provider rejection.
5. Historical implementations differ: WildChat used runner 0.3.0 before chunking; long-context runs used 0.4.0; tool runs used 0.5.0 with dependency closure. All published runs use the same Noul prompt, threshold, and chronological omission. The current cleaned runner incorporates the latest functionality; a rerun is not byte-identical historical software replay.
6. Recorded messages can contain mistakes and stale information. Source assistant answers are not reliable ground truth.
7. Timing depends on provider load, caching, output length, and serialization overhead. Costs are estimates. Availability of the historical main-model identifier is not independently established for other accounts.
8. Released evidence is sanitized; original hashes describe pre-release records, while release checksums cover distributed bytes. No new inference was performed during publication cleanup.

## Verification and next work

Readers can verify benchmark integrity, input/target alignment, ordering, protocol validity, prompt equality, and released checksums offline. They can regenerate the tables and inspect paired answers in the reviewer. This verifies experimental records and accounting, not answer truth.

Next research steps are systematic grading, held-out cases, threshold sensitivity, and stronger tool-evidence tasks. Building a coding agent around persistent history, selective compaction, and a message graph is future work and is not an implemented or evaluated claim of this release.
