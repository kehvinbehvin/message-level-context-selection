"""Whole-message partitioning; byte budgets are conservative proxies, not token counts."""
import copy
from .core import canonical, jev_request
from .tool_messages import message_groups


def request_size(request):
    state = len(canonical(request['state']).encode('utf-8'))
    longest = max((len(canonical(q).encode('utf-8')) for q in request['questions'].values()), default=0)
    return {'state_plus_longest_question_bytes': state + longest,
            'request_bytes': len(canonical(request).encode('utf-8'))}


def plan_chunks(case, config):
    """Plan all chunks before issuing requests, so impossible inputs fail without partial curation."""
    policy = config['chunking']
    ids = case['source']['history_message_ids']
    history = case['input']['history_messages']
    def make(start, end):
        part = {'input': {'history_messages': history[start:end],
                          'target_user_message': case['input']['target_user_message']},
                'source': {'history_message_ids': ids[start:end]}}
        request = jev_request(part, config)
        size = request_size(request)
        return {'message_ids': ids[start:end], 'size': size, 'request': request}
    def fits(chunk):
        size = chunk['size']
        return (size['state_plus_longest_question_bytes'] <= policy['state_question_byte_budget'] and
                size['request_bytes'] <= policy['request_byte_budget'])
    if not ids:
        return []
    boundaries = [g[-1] + 1 for g in message_groups(history)]
    chunks = []
    start = 0
    group_index = 0
    while start < len(ids):
        single = make(start, boundaries[group_index])
        if not fits(single):
            raise ValueError(f'Message or tool group starting at {ids[start]} cannot fit with the target and instructions in one Jev chunk. No message was split or truncated.')
        # Binary search the largest contiguous prefix that satisfies both budgets.
        low, high, best = group_index, len(boundaries) - 1, single
        best_index = group_index
        while low <= high:
            index = (low + high) // 2
            candidate = make(start, boundaries[index])
            if fits(candidate):
                best = candidate
                best_index = index
                low = index + 1
            else:
                high = index - 1
        chunks.append(copy.deepcopy(best))
        start += len(best['message_ids'])
        group_index = best_index + 1
    return chunks
