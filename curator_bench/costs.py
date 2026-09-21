"""List-price estimates using the pricing snapshot verified on 2026-09-20."""

PRICING = {
    'verified_on': '2026-09-20',
    'currency': 'USD',
    'terra_per_million': {'input': 2.0, 'cached_input': 0.20, 'cache_write': 2.50, 'output': 12.0},
    'jev_per_million': {'input': 0.042, 'output': 0.0},
    'sources': ['https://developers.openai.com/api/docs/pricing',
                'https://typesafe.ai/blog/introducing-system-one-models-and-jev'],
    'note': 'Estimates before credits, discounts or taxes. Includes all recorded attempts and reasoning output tokens. Unknown usage or unsupported pricing is unavailable. Offline fixtures have no API cost estimate.',
}


def stage_cost(stage, kind):
    if not stage or not stage.get('attempts'):
        return None
    total = 0.0
    for attempt in stage['attempts']:
        response = attempt.get('response') or {}
        usage = response.get('usage') or {}
        if kind == 'jev':
            if stage.get('url') != 'https://api.typesafe.ai/v1/systemone':
                return None
            tokens = usage.get('input_tokens')
            if not isinstance(tokens, int) or tokens < 0:
                return None
            total += tokens * 0.042 / 1_000_000
        else:
            if stage.get('url') != 'https://api.openai.com/v1/chat/completions' or response.get('model') != 'gpt-5.6-terra' or response.get('service_tier', 'default') not in ('default', 'auto'):
                return None
            prompt, output = usage.get('prompt_tokens'), usage.get('completion_tokens')
            if not all(isinstance(n, int) and n >= 0 for n in (prompt, output)):
                return None
            # Only short-context pricing is supported by this snapshot.
            if prompt > 128_000:
                return None
            detail = usage.get('prompt_tokens_details') or {}
            cached, writes = detail.get('cached_tokens'), detail.get('cache_write_tokens')
            if not all(isinstance(n, int) and n >= 0 for n in (cached, writes)) or cached + writes > prompt:
                return None
            total += ((prompt - cached - writes) * 2 + cached * .2 + writes * 2.5 + output * 12) / 1_000_000
    return total


def branch_cost(branch, name, offline=False):
    if offline or not branch:
        return {'completion': None, 'jev': None, 'total': None}
    completion = stage_cost(branch.get('completion'), 'completion')
    jev = 0.0 if name == 'without_jev' else stage_cost(branch.get('jev'), 'jev')
    # Empty histories skip Jev entirely.
    if name == 'with_jev' and 'jev' not in branch and branch.get('curation', {}).get('original_message_count') == 0:
        jev = 0.0
    total = completion + jev if completion is not None and jev is not None else None
    return {'completion': completion, 'jev': jev, 'total': total}
