"""Validation and atomic groups for recorded Chat Completions tool exchanges."""
import json
import re


def message_groups(messages):
    groups, pending, seen, group = [], set(), set(), []
    for i, m in enumerate(messages):
        role = m.get('role')
        if not isinstance(m.get('content'), str):
            raise ValueError('Recorded messages require string content.')
        if pending:
            if role != 'tool' or set(m) != {'role', 'content', 'tool_call_id'}:
                raise ValueError('Tool calls must be followed by their results.')
            cid = m['tool_call_id']
            if cid not in pending:
                raise ValueError('Orphan or duplicate tool result.')
            pending.remove(cid)
            group.append(i)
            if not pending:
                groups.append(group)
            continue
        if role == 'assistant' and 'tool_calls' in m:
            if set(m) != {'role', 'content', 'tool_calls'} or not isinstance(m['tool_calls'], list) or not m['tool_calls']:
                raise ValueError('Invalid tool call message.')
            group = [i]
            for call in m['tool_calls']:
                if set(call) != {'id', 'type', 'function'} or call['type'] != 'function':
                    raise ValueError('Invalid recorded function call.')
                cid, f = call['id'], call['function']
                if not isinstance(cid, str) or not cid or cid in seen:
                    raise ValueError('Duplicate or invalid call ID.')
                if set(f) != {'name', 'arguments'} or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', f['name']):
                    raise ValueError('Invalid function name/fields.')
                if not isinstance(f['arguments'], str) or not isinstance(json.loads(f['arguments']), dict):
                    raise ValueError('Function arguments must encode an object.')
                seen.add(cid)
                pending.add(cid)
        elif role in {'user', 'assistant'} and set(m) == {'role', 'content'}:
            groups.append([i])
        else:
            raise ValueError('Unsupported message or orphan tool result.')
    if pending:
        raise ValueError('Missing tool result.')
    return groups


def display_content(message):
    text = message['content']
    if message.get('tool_calls'):
        text += '\n\nRecorded tool calls:\n' + json.dumps(message['tool_calls'], ensure_ascii=False, indent=2)
    if message.get('tool_call_id'):
        text = 'Result for ' + message['tool_call_id'] + '\n' + text
    return text
