# Method specification

## Exact Noul question

The `{message_id}` placeholder is replaced with the original history message ID for each question:

> Does this message help determine what the answer should contain, what the request means, or what an acceptable answer must satisfy? Consider the entire conversation and minimise duplicate information. Preserve messages that clarify conversational flow, the user’s intent, or changes in intent only when understanding those aspects helps answer the current user message—for example, by resolving a relevant reference, connecting necessary information, or clarifying an applicable goal or requirement. This message is state.history's message with id {message_id}; the user's message is state.target_user_message.

Jev receives the original ordered history and the target user message in shared `state`. Each question has `type: noul`; no score levels are used. The threshold is inclusive: probability ≥ 0.5. Questions ask about contribution to the answer, request meaning, and acceptable-answer requirements, including useful flow and intent. They also ask Jev to minimize duplication. This is an instruction, not a guarantee of globally consistent duplicate elimination.

## Context assembly

Selection omits whole messages and never sorts by probability. The target and shared main-model instruction are always included. Empty history selection is allowed. For recorded tools, any selected member retains its entire contiguous assistant call / associated result group. Dependency closure is reported separately from model probabilities. The call/result group is indivisible for chunking too. No commands execute and no tools are offered for new calls.

The chunker greedily finds the largest contiguous group prefix fitting both budgets using binary search. Every chunk repeats the unchanged target and per-message question. There is no overlap or second pass. The budgets are 28,000 UTF-8 bytes for serialized state plus the longest question and 56,000 bytes for the whole serialized request. They are conservative proxies, not true tokenizer counts or guaranteed provider bounds. Oversized individual groups fail rather than being shortened. Three released tool cases fail this local check.

The archived WildChat run predates chunking; long-context and tool runs use it. Current code preflights tool-group fit before either branch incurs charges. Versions are recorded in each results manifest. The current release removes legacy approaches without changing the Noul prompt.

## What is measured

The paired answer, provider-reported input/output usage, Jev decisions and request/response, chunk boundaries, whole-branch wall time, component times, and estimated costs. Relevance probabilities are model outputs; no task-specific calibration study is claimed. Quality requires separate evaluation; successful HTTP completion is not an accuracy metric.
