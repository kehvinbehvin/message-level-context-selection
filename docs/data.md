# Data sources and release notes

## WildChat

Source: [allenai/WildChat](https://huggingface.co/datasets/allenai/WildChat), Wenting Zhao and collaborators, *WildChat: 1M ChatGPT Interaction Logs in the Wild*, ICLR 2024.

Acquisition: first 100 viewer rows returned for English conversations with at least 20 turns; a convenience sample, not random sampling. Eight conversations were reviewed and mined into 20 selected follow-up cases. Source conversation IDs, row references, original message IDs, and hashes are embedded in `benchmarks/wildchat.json`. The viewer endpoint was not revision-pinned; the manifest's observed repository revision does not prove the returned row revision.

The source declares ODC-BY. [License text](../benchmarks/provenance/wildchat-LICENSE.md), [saved card](../benchmarks/provenance/wildchat-card.md), and [acquisition manifest](../benchmarks/provenance/wildchat-manifest.json) are included. The database license does not relicense every embedded third-party text. Retain source attribution when redistributing. Only selected cases are included, not the full downloaded exploration pool.

## LongMemEval

Source: [xiaowu0162/LongMemEval](https://github.com/xiaowu0162/LongMemEval), with records from [xiaowu0162/longmemeval-cleaned](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned), revision `98d7416c24c778c2fee6e6f3006e7a073259d48f`.

The selected parent records are `031748ae`, `6d550036`, and `gpt4_2655b836`. Nine cases reuse original memory questions or historical follow-ups. Each input message has a neutral session/date prefix; otherwise source content and source session order are preserved. Metadata identifies the adaptation. Sessions are constructed, not an organic continuous user history, and may involve different personas. Parent overlap prevents treating the nine cases as independent samples.

The source declares MIT. See the [source manifest](../benchmarks/provenance/longmemeval-manifest.json), [saved card](../benchmarks/provenance/longmemeval-card.md), and bundled source license. Evaluation-only evidence annotations are not sent to the models.

## Authorized conversation with tool results

The author explicitly authorized use and public release of this research conversation. Five existing questions were selected from bounded chronological episodes of its saved transcript. This is project-specific, hand-selected data; it is not representative of coding conversations in general.

`benchmarks/tool-use.json` includes the five cases, source message mappings, and draft grading rubrics. Only two have live results; three are blocked by the byte-budget proxy. Internal reasoning, system/developer messages, ambient browser context, and internal session metadata are excluded. Tool inputs are literal strings inside `function.arguments.recorded_input`, with linked native call/result envelopes. The commands are not executed. Source truncation remains where it existed in the transcript.

Known credentials, email patterns, and local home-directory identifiers were redacted. The raw private session and its export/mining script are not distributed. The original public-reviewed draft was subsequently adapted to the runner format; the published benchmark is the canonical distributed input. The conversation is shared with its author's permission, but third-party excerpts retain their own rights. The code's MIT license is not a blanket license over those excerpts.

## Evidence integrity and privacy

Publication normalization changes local home-directory names in six files. Recorded probabilities, response metrics, timings, and token counts are not recalculated as if requests were rerun. `results/redactions.json` records affected files and pre-release file hashes. Input checksums were refreshed where content changed, preserving original hashes separately. Case records carry both historical and released benchmark hashes.

The release checksum manifest covers published evidence bytes. Model input content is visible for verification, subject to those documented redactions. Saved source metadata may contain historical URLs that no longer resolve; these are provenance, not runtime dependencies. User-facing model text is untrusted experimental content, not instructions for the repository's tools.
