"""Input isolation, scoring contract, selection and configuration. No API calls."""
from .tool_messages import message_groups
import copy
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import urlparse

NOUL_INSTRUCTION = (
    "Does this message help determine what the answer should contain, what the request means, or what an acceptable answer must satisfy? "
    "Consider the entire conversation and minimise duplicate information. Preserve messages that clarify conversational flow, the user’s intent, or changes in intent only when understanding those aspects helps answer the current user message—for example, by resolving a relevant reference, connecting necessary information, or clarifying an applicable goal or requirement. "
    "This message is state.history's message with id {message_id}; "
    "the user's message is state.target_user_message."
)

DEFAULTS = {
    'benchmark': '../benchmarks/wildchat.json', 'model': None,
    'openai_base_url': 'https://api.openai.com/v1', 'openai_key_env': 'OPENAI_API_KEY',
    'jev_endpoint': 'https://api.typesafe.ai/v1/systemone', 'jev_key_env': 'TYPESAFE_API_KEY',
    'jev_model': 'jev-latest',
    'system_message': 'Answer the current user request accurately using relevant history. No tools are available.',
    'instruction_role': 'system', 'completion_parameters': {'max_completion_tokens': 2048},
    'curation': {'mode': 'omit_only', 'decision_type': 'noul', 'min_probability': 0.5, 'order': 'chronological'},
    'chunking': {'state_question_byte_budget': 28000, 'request_byte_budget': 56000},
    'timeout_seconds': 120, 'max_retries': 0, 'retry_backoff_seconds': 1, 'case_ids': [],
}
PARAMETERS = {'temperature', 'top_p', 'max_completion_tokens', 'reasoning_effort', 'seed',
              'frequency_penalty', 'presence_penalty', 'verbosity'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def config_from_file(path):
    path = Path(path).resolve()
    overrides = json.loads(path.read_text())
    if not isinstance(overrides, dict) or set(overrides) - set(DEFAULTS):
        raise ValueError('Configuration must be an object containing only documented fields.')
    config = copy.deepcopy(DEFAULTS)
    config.update(overrides)
    config['benchmark'] = str((path.parent / config['benchmark']).resolve())
    return config


def validate_config(c, offline=False):
    if set(c) != set(DEFAULTS):
        raise ValueError('Unexpected or missing configuration fields.')
    if not offline and (not isinstance(c['model'], str) or not c['model'].strip()):
        raise ValueError('Choose a model in config or with --model before a live run.')
    for key in ['jev_model', 'system_message']:
        if not isinstance(c[key], str) or not c[key].strip():
            raise ValueError(f'{key} must be a nonempty string.')
    if c['instruction_role'] not in {'system', 'developer'}:
        raise ValueError('instruction_role must be system or developer.')
    for key in ['openai_key_env', 'jev_key_env']:
        if not isinstance(c[key], str) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', c[key]):
            raise ValueError(f'{key} must be an environment variable name, not a credential.')
    for key in ['openai_base_url', 'jev_endpoint']:
        url = urlparse(c[key])
        if not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError(f'{key} must be a plain endpoint without credentials/query/fragment.')
        if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in {'localhost', '127.0.0.1', '::1'}):
            raise ValueError(f'{key} must use HTTPS (HTTP allowed only on loopback).')
    if not isinstance(c['completion_parameters'], dict) or set(c['completion_parameters']) - PARAMETERS:
        raise ValueError('Unsupported completion_parameters; messages/model/stream/n/tools are controlled by the runner.')
    canonical(c['completion_parameters'])
    p = c['curation']
    if not isinstance(p, dict):
        raise ValueError('curation must be an object.')
    if set(p) != {'mode', 'order', 'decision_type', 'min_probability'} or p.get('decision_type') != 'noul':
        raise ValueError('Only Noul selection is supported.')
    if p['mode'] != 'omit_only' or p['order'] != 'chronological':
        raise ValueError('Only chronological omission is supported.')
    if not finite(p['min_probability']) or not 0 <= p['min_probability'] <= 1:
        raise ValueError('Probability threshold must be between 0 and 1.')
    chunking = c['chunking']
    limits = {'state_question_byte_budget': 28000, 'request_byte_budget': 56000}
    if not isinstance(chunking, dict) or set(chunking) != set(limits):
        raise ValueError('chunking requires state_question_byte_budget and request_byte_budget.')
    for key, limit in limits.items():
        if type(chunking[key]) is not int or not 1 <= chunking[key] <= limit:
            raise ValueError(f'{key} must be a positive integer no greater than {limit}.')
    for key in ['timeout_seconds', 'retry_backoff_seconds']:
        if not finite(c[key]) or c[key] <= 0:
            raise ValueError(f'{key} must be positive and finite.')
    if type(c['max_retries']) is not int or not 0 <= c['max_retries'] <= 5:
        raise ValueError('max_retries must be an integer from 0 through 5.')
    if not isinstance(c['case_ids'], list) or any(not isinstance(x, str) for x in c['case_ids']) or len(c['case_ids']) != len(set(c['case_ids'])):
        raise ValueError('case_ids must be a list of unique strings.')


def load_benchmark(path, selected_ids=()):
    benchmark = json.loads(Path(path).read_text())
    cases = benchmark['cases']
    if not isinstance(cases, list) or not cases:
        raise ValueError('Benchmark needs a nonempty cases list.')
    seen = set()
    for case in cases:
        cid = case['case_id']
        if not isinstance(cid, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', cid) or cid in seen:
            raise ValueError('Duplicate or unsafe case ID.')
        seen.add(cid)
        inp = case['input']
        history = inp['history_messages']
        target = inp['target_user_message']
        ids = case['source']['history_message_ids']
        if not isinstance(history, list) or len(history) != len(ids) or len(ids) != len(set(ids)):
            raise ValueError(f'{cid}: invalid history ID mapping.')
        for mid in ids:
            if not isinstance(mid, str) or not re.fullmatch(r'm[0-9]+', mid):
                raise ValueError(f'{cid}: invalid message ID.')
        target_id = case['source']['target_message_id']
        if not re.fullmatch(r'm[0-9]+', target_id):
            raise ValueError(f'{cid}: invalid target ID.')
        if ids != [f'm{i:04d}' for i in range(1, len(history) + 1)] or int(target_id[1:]) != len(history) + 1:
            raise ValueError(f'{cid}: history must be a contiguous prefix before the target.')
        message_groups(history)
        if set(target) != {'role', 'content'} or not isinstance(target['content'], str):
            raise ValueError(f'{cid}: invalid target message.')
        if target['role'] != 'user':
            raise ValueError(f'{cid}: target must be a user message.')
        if sha(inp) != case['integrity']['input_sha256']:
            raise ValueError(f'{cid}: input hash mismatch.')
    wanted = set(selected_ids)
    if wanted - seen:
        raise ValueError('Requested case IDs not found in benchmark.')
    selected = [c for c in cases if not wanted or c['case_id'] in wanted]
    return benchmark, selected


def jev_request(case, config):
    history = case['input']['history_messages']
    ids = case['source']['history_message_ids']
    return {
        'model': config['jev_model'],
        'state': {
            'history': [dict(id=mid, **copy.deepcopy(m)) for mid, m in zip(ids, history)],
            'target_user_message': copy.deepcopy(case['input']['target_user_message']),
        },
        # Question keys are NOT seen by Jev: name each ID in the instructions too.
        'questions': {mid: {'type': 'noul', 'instructions': NOUL_INSTRUCTION.format(message_id=mid)} for mid in ids},
    }


def parse_nouls(response, ids):
    answers = response.get('answers')
    if not isinstance(answers, dict) or set(answers) != set(ids):
        raise ValueError('Jev must return exactly one answer for each original message ID.')
    decisions = {}
    for mid in ids:
        answer = answers[mid]
        if not isinstance(answer, dict) or answer.get('type') != 'noul' or not finite(answer.get('noul')) or not 0 <= answer['noul'] <= 1:
            raise ValueError(f'Invalid Jev Noul for {mid}.')
        decisions[mid] = {'type': 'noul', 'noul': answer['noul']}
    return decisions


def curate(case, scores, policy):
    ids = case['source']['history_message_ids']
    if set(scores) != set(ids):
        raise ValueError('Scores do not match history IDs.')
    if policy['mode'] != 'omit_only' or policy['order'] != 'chronological':
        raise ValueError('Reordering is disabled; use omit_only with chronological order.')
    selected = [mid for mid in ids if scores[mid]['noul'] >= policy['min_probability']]
    independently_selected = set(selected)
    for group in message_groups(case['input']['history_messages']):
        if any(ids[i] in independently_selected for i in group):
            selected.extend(ids[i] for i in group if ids[i] not in selected)
    selected = [mid for mid in ids if mid in selected]
    mapping = dict(zip(ids, case['input']['history_messages']))
    return {
        'decisions': scores, 'selected_message_ids': selected,
        'dropped_message_ids': [mid for mid in ids if mid not in selected],
        'history_messages': [copy.deepcopy(mapping[mid]) for mid in selected],
        'dependency_retained_message_ids': [mid for mid in selected if mid not in independently_selected],
        'tool_group_policy': 'retain entire call/results group if any member passes threshold',
        'policy': copy.deepcopy(policy),
        'original_message_count': len(ids), 'retained_message_count': len(selected),
        'order_changed': selected != [mid for mid in ids if mid in selected],
        'context_unchanged': selected == ids,
    }


def completion_request(case, history, config):
    message_groups(history)
    return dict(config['completion_parameters'], model=config['model'], stream=False, n=1, store=False,
                messages=[{'role': config['instruction_role'], 'content': config['system_message']}] +
                         copy.deepcopy(history) + [copy.deepcopy(case['input']['target_user_message'])])


def completion_answer(response):
    choices = response.get('choices')
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError('Expected exactly one Chat Completions choice.')
    choice = choices[0]
    message = choice.get('message', {})
    if not isinstance(message, dict):
        raise ValueError('Completion message must be an object.')
    content, refusal = message.get('content'), message.get('refusal')
    if message.get('tool_calls') or message.get('function_call'):
        raise ValueError('Tool calls are not enabled for this benchmark.')
    if not isinstance(content, str) and not isinstance(refusal, str):
        raise ValueError('Completion has neither text nor refusal.')
    return {'text': content or refusal or '', 'refusal': refusal,
            'finish_reason': choice.get('finish_reason'),
            'truncated': choice.get('finish_reason') == 'length',
            'returned_model': response.get('model'), 'response_id': response.get('id')}


def usage(response):
    raw = response.get('usage') or {}
    if not isinstance(raw, dict):
        raw = {}
    def count(*keys):
        for key in keys:
            v = raw.get(key)
            if type(v) is int and v >= 0:
                return v
        return None
    return {'input_tokens': count('input_tokens', 'prompt_tokens'),
            'output_tokens': count('output_tokens', 'completion_tokens'), 'raw': raw}


def aggregate_usage(stages):
    attempts = [a for s in stages for a in s.get('attempts', [])]
    result = {'attempt_count': len(attempts)}
    for field in ['input_tokens', 'output_tokens']:
        values = [a.get('usage', {}).get(field) for a in attempts]
        complete = all(v is not None for v in values)
        result[field] = sum(values) if complete else None
        result['observed_' + field] = sum(v for v in values if v is not None)
        result[field + '_complete'] = complete
    result['note'] = 'Totals are unavailable when any attempt lacks usage. Observed subtotals may undercount failed/timeout requests.'
    return result
