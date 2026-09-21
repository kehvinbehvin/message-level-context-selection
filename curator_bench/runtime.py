"""Auditable HTTP calls, incremental storage, and paired execution."""
import copy
import datetime
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from . import __version__
from .chunking import plan_chunks
from .core import (NOUL_INSTRUCTION, parse_nouls, aggregate_usage, canonical, completion_answer,
                   completion_request, curate, jev_request, sha, usage)


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Store:
    def __init__(self, root, secrets=()):
        self.root = Path(root)
        self.secrets = [s for s in secrets if s]

    def clean(self, value):
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, '[REDACTED_CREDENTIAL]')
            return value
        if isinstance(value, list):
            return [self.clean(x) for x in value]
        if isinstance(value, dict):
            return {k: self.clean(v) for k, v in value.items()}
        return value

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + '.tmp')
        with temp.open('w') as f:
            json.dump(self.clean(value), f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)


def decode_body(raw):
    text = raw.decode('utf-8', errors='replace')
    try:
        def reject_constant(value):
            raise ValueError('Non-finite JSON constant')
        value = json.loads(text, parse_constant=reject_constant)
        if isinstance(value, dict):
            return value, None
    except (ValueError, TypeError):
        pass
    return None, text


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Do not forward credentials to a redirect target.


class HTTPTransport:
    def __init__(self, openai_key, jev_key):
        self.keys = {'openai': openai_key, 'jev': jev_key}
        self.opener = urllib.request.build_opener(NoRedirect)

    def post(self, service, url, body, timeout):
        request = urllib.request.Request(url, data=canonical(body).encode(), method='POST', headers={
            'Authorization': 'Bearer ' + self.keys[service], 'Content-Type': 'application/json',
            'User-Agent': 'jev-context-benchmark/' + __version__,
        })
        try:
            with self.opener.open(request, timeout=timeout) as response:
                payload, raw_text = decode_body(response.read())
                return {'http_status': response.status, 'response': payload, 'raw_response_text': raw_text,
                        'request_id': response.headers.get('x-request-id'),
                        'retryable': False, 'transport_error': None}
        except urllib.error.HTTPError as exc:
            with exc:
                payload, raw_text = decode_body(exc.read())
            return {'http_status': exc.code, 'response': payload, 'raw_response_text': raw_text,
                    'request_id': exc.headers.get('x-request-id') if exc.headers else None,
                    'retryable': exc.code in {408, 409, 429} or exc.code >= 500,
                    'transport_error': 'HTTP request failed'}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Exception strings can contain sensitive proxy URLs. Record only safe type.
            return {'http_status': None, 'response': None, 'raw_response_text': None,
                    'request_id': None, 'retryable': True, 'transport_error': type(exc).__name__}


class OfflineTransport:
    """Deterministic fixtures exercise plumbing only; not model/curator quality."""
    def post(self, service, url, body, timeout):
        if service == 'jev':
            answers = {}
            for message in body['state']['history']:
                score = int(hashlib.sha256(message['content'].encode()).hexdigest()[:8], 16) % 5
                answers[message['id']] = {'type': 'noul', 'noul': score / 4}
            response = {'model': 'offline-jev-fixture', 'answers': answers,
                        'usage': {'input_tokens': len(canonical(body)) // 4, 'output_tokens': len(answers) * 5},
                        'fixture': True}
        else:
            text = ('OFFLINE FIXTURE — not a model answer.\n'
                    f'Received {len(body["messages"]) - 2} historical messages.\n'
                    'Target: ' + body['messages'][-1]['content'])
            response = {'id': 'offline-' + sha(body)[:12], 'model': 'offline-completion-fixture',
                        'choices': [{'message': {'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}],
                        'usage': {'prompt_tokens': len(canonical(body)) // 4, 'completion_tokens': len(text) // 4},
                        'fixture': True}
        return {'http_status': 200, 'response': response, 'raw_response_text': None,
                'request_id': 'offline-fixture', 'retryable': False, 'transport_error': None}


def execute_stage(service, url, request, config, transport, branch, key, save, parser):
    start = time.perf_counter()
    stage = {'service': service, 'url': url, 'request': request, 'status': 'running',
             'started_at': utc(), 'duration_seconds': None, 'attempts': [], 'parsed': None}
    branch[key] = stage
    save()
    for number in range(config['max_retries'] + 1):
        attempt = {'number': number + 1, 'status': 'in_flight', 'started_at': utc(), 'duration_seconds': None}
        stage['attempts'].append(attempt)
        save()  # Persist before dispatch; an interrupted request has an unknown outcome.
        t0 = time.perf_counter()
        try:
            result = transport.post(service, url, request, config['timeout_seconds'])
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            result = {'http_status': None, 'response': None, 'retryable': False,
                      'transport_error': type(exc).__name__, 'request_id': None, 'raw_response_text': None}
        attempt.update(result)
        attempt['duration_seconds'] = time.perf_counter() - t0
        attempt['finished_at'] = utc()
        response = result.get('response')
        attempt['usage'] = usage(response) if isinstance(response, dict) else usage({})
        http_ok = result.get('http_status') is not None and 200 <= result['http_status'] < 300
        if http_ok and not result.get('transport_error'):
            try:
                if not isinstance(response, dict):
                    raise ValueError('API returned a non-object or invalid JSON response.')
                stage['parsed'] = parser(response)
                stage['status'] = 'succeeded'
                attempt['status'] = 'succeeded'
            except (ValueError, KeyError, TypeError) as exc:
                attempt['status'] = 'invalid_response'
                stage['status'] = 'failed'
                stage['error'] = str(exc)
            save()
            break  # Do not retry semantic/schema failures or truncated answers.
        attempt['status'] = 'failed'
        save()
        if not result.get('retryable') or number == config['max_retries']:
            stage['status'] = 'failed'
            stage['error'] = result.get('transport_error') or 'API request failed'
            break
        delay = config['retry_backoff_seconds'] * 2 ** number
        attempt['retry_delay_seconds'] = delay
        save()
        time.sleep(delay)
    stage['duration_seconds'] = time.perf_counter() - start
    stage['finished_at'] = utc()
    stage['usage'] = aggregate_usage([stage])
    save()
    return stage


def finish_branch(branch, start):
    branch['duration_seconds'] = time.perf_counter() - start
    branch['finished_at'] = utc()
    stages = [branch[k] for k in ['jev', 'completion'] if k in branch]
    branch['usage'] = aggregate_usage(stages)
    branch['timings'] = {
        'end_to_end_seconds': branch['duration_seconds'],
        'jev_seconds': branch.get('jev', {}).get('duration_seconds'),
        'completion_seconds': branch.get('completion', {}).get('duration_seconds'),
    }


def execute_jev_chunks(case, config, transport, branch, save):
    chunks = plan_chunks(case, config)
    branch['chunk_plan'] = {
        'method': 'nonoverlapping_whole_messages',
        'sizing': 'UTF-8 bytes of canonical JSON; conservative proxy, not Jev tokens; no guaranteed token fit',
        'budgets': copy.deepcopy(config['chunking']),
        'chunk_count': len(chunks),
        'chunks': [{k: v for k, v in chunk.items() if k != 'request'} for chunk in chunks],
    }
    save()
    parser = parse_nouls
    if len(chunks) == 1:
        chunk = chunks[0]
        return execute_stage('jev', config['jev_endpoint'], chunk['request'], config,
                             transport, branch, 'jev', save, lambda r: parser(r, chunk['message_ids']))
    start = time.perf_counter()
    stage = {'service': 'jev', 'url': config['jev_endpoint'], 'status': 'running',
             'started_at': utc(), 'duration_seconds': None, 'chunks': {}, 'attempts': [], 'parsed': {}}
    branch['jev'] = stage
    def sync_save():
        # Flat attempts support existing usage/cost consumers. Nested stages preserve provenance.
        stage['attempts'] = [attempt for chunk in stage['chunks'].values() for attempt in chunk['attempts']]
        stage['usage'] = aggregate_usage([stage])
        save()
    sync_save()
    for i, chunk in enumerate(chunks, 1):
        result = execute_stage('jev', config['jev_endpoint'], chunk['request'], config,
                               transport, stage['chunks'], f'chunk_{i:04d}', sync_save,
                               lambda r, ids=chunk['message_ids']: parser(r, ids))
        if result['status'] != 'succeeded':
            stage.update(status='failed', error=f'Chunk {i} failed; no partial curated completion will be sent.')
            break
        stage['parsed'].update(result['parsed'])
        sync_save()
    else:
        stage['status'] = 'succeeded'
    stage['duration_seconds'] = time.perf_counter() - start
    stage['finished_at'] = utc()
    sync_save()
    return stage


def execute_branch(name, case, config, transport, record, save):
    start = time.perf_counter()
    branch = {'status': 'running', 'started_at': utc(), 'duration_seconds': None}
    record['branches'][name] = branch
    save()
    history = case['input']['history_messages']
    if name == 'with_jev':
        ids = case['source']['history_message_ids']
        if ids:
            try:
                jev = execute_jev_chunks(case, config, transport, branch, save)
            except ValueError as exc:
                branch.update(status='failed', error=str(exc))
                finish_branch(branch, start)
                save()
                return
            if jev['status'] != 'succeeded':
                branch.update(status='failed', error='Jev failed; curated completion was not issued. No baseline fallback.')
                finish_branch(branch, start)
                save()
                return
            scores = jev['parsed']
        else:
            scores = {}
        branch['curation'] = curate(case, scores, config['curation'])
        history = branch['curation']['history_messages']
        save()
    stage = execute_stage('openai', config['openai_base_url'].rstrip('/') + '/chat/completions',
                          completion_request(case, history, config), config, transport,
                          branch, 'completion', save, completion_answer)
    branch['status'] = stage['status']
    if stage['status'] == 'succeeded':
        branch['answer'] = stage['parsed']
    else:
        branch['error'] = 'Completion failed; inspect the recorded attempt.'
    finish_branch(branch, start)
    save()


def compare(record):
    branches = record['branches']
    a, b = branches.get('without_jev', {}), branches.get('with_jev', {})
    def completion_input(branch):
        stage = branch.get('completion', {})
        if stage.get('status') != 'succeeded':
            return None
        return stage['attempts'][-1]['usage']['input_tokens']
    full, curated = completion_input(a), completion_input(b)
    comparable = a.get('status') == b.get('status') == 'succeeded'
    return {
        'both_branches_succeeded': comparable,
        'main_completion_input_tokens_saved': full - curated if comparable and full is not None and curated is not None else None,
        'main_completion_input_reduction_fraction': (full - curated) / full if comparable and full and curated is not None else None,
        'note': 'Main-completion savings exclude Jev overhead; consult whole-branch usage. These metrics do not measure answer quality.',
    }


def run(config, benchmark, cases, output, offline=False, resume=False, transport=None):
    from .report import render_report
    # Preflight tool histories before either branch can incur a charge.
    for case in cases:
        if any('tool_calls' in m for m in case['input']['history_messages']):
            plan_chunks(case, config)
    output = Path(output).resolve()
    keys = [] if offline else [os.environ.get(config[k], '') for k in ['openai_key_env', 'jev_key_env']]
    if not offline and not all(keys):
        raise ValueError('Live run needs both configured API-key environment variables. No request was issued.')
    effective = copy.deepcopy(config)
    if offline:
        effective['model'] = 'offline-completion-fixture'
    identity = {'config': effective, 'benchmark_sha256': sha(benchmark),
                'case_ids': [c['case_id'] for c in cases], 'offline': offline,
                'decision_type': 'noul',
                'selection_instruction': NOUL_INSTRUCTION,
                'runner_version': __version__}
    store = Store(output, keys)
    if resume:
        manifest = json.loads((output / 'manifest.json').read_text())
        if manifest['run_identity_sha256'] != sha(identity):
            raise ValueError('Cannot resume: benchmark, case selection, config, mode or prompt changed.')
    else:
        output.mkdir(parents=True, exist_ok=False)
        manifest = {'schema_version': '1.0.0', 'run_id': output.name, 'created_at': utc(),
                    'status': 'running', 'run_identity_sha256': sha(identity), **identity,
                    'sources': {'openai': 'https://developers.openai.com/api/reference/resources/chat',
                                'jev': 'https://docs.typesafe.ai/api'},
                    'measurement_notes': [
                        'Sequential execution; first branch alternates by selected case index.',
                        'Wall-clock timings use perf_counter. Branch/stage times include request preparation, persistence and retry backoff as applicable; attempt time covers transport call.',
                        'Requests are non-streaming. Completion time ends after the full response body is received and decoded.',
                        'Default is no retries. Missing token usage is null, not zero. Failed requests may have consumed unreported tokens.',
                        'Offline scores, answers and usage are synthetic fixtures. Timings measure fixture execution, not provider latency.',
                        'No tool calls are enabled. Annotation metadata never enters model requests.',
                        'Jev chunking uses conservative UTF-8 byte budgets, not exact tokenizer counts. Chunk boundaries and per-chunk traces are recorded; cross-chunk dependencies are unavailable to Jev.',
                        'Prompt caching can affect timing; raw provider usage, including cache/reasoning details when supplied, is retained.',
                    ]}
        store.write('manifest.json', manifest)
        store.write('benchmark.snapshot.json', benchmark)
    manifest['status'] = 'running'
    manifest.setdefault('sessions', []).append({'started_at': utc()})
    store.write('manifest.json', manifest)
    transport = transport or (OfflineTransport() if offline else HTTPTransport(*keys))
    try:
        for index, case in enumerate(cases):
            path = output / 'cases' / (case['case_id'] + '.json')
            if path.exists():
                record = json.loads(path.read_text())
                # Never automatically resend an interrupted/in-flight request: its billing/outcome is unknown.
                for branch in record['branches'].values():
                    if branch['status'] == 'running':
                        branch.update(status='interrupted', error='Previous request outcome is unknown; not replayed on resume.')
                        branch['usage'] = aggregate_usage([branch[k] for k in ['jev', 'completion'] if k in branch])
            else:
                order = ['without_jev', 'with_jev'] if index % 2 == 0 else ['with_jev', 'without_jev']
                record = {'schema_version': '1.0.0', 'case_id': case['case_id'], 'title': case['title'],
                          'category_id': case['category_id'], 'offline': offline,
                          'target_user_message': case['input']['target_user_message'],
                          'original_history_messages': case['input']['history_messages'],
                          'original_history_message_ids': case['source']['history_message_ids'],
                          'branch_order': order, 'created_at': utc(), 'branches': {},
                          'benchmark_input_sha256': case['integrity']['input_sha256']}
            def save():
                store.write('cases/' + case['case_id'] + '.json', record)
            save()
            for name in record['branch_order']:
                if name in record['branches']:
                    continue
                execute_branch(name, case, effective, transport, record, save)
            record['comparison'] = compare(record)
            record['usage'] = aggregate_usage([b[k] for b in record['branches'].values() for k in ['jev', 'completion'] if k in b])
            durations = [b.get('duration_seconds') for b in record['branches'].values()]
            record['combined_branch_duration_seconds'] = sum(durations) if all(x is not None for x in durations) else None
            record['finished_at'] = utc()
            save()
            render_report(output)
            print(f'[{index + 1}/{len(cases)}] {case["case_id"]}: ' + ', '.join(f'{k}={v["status"]}' for k,v in record['branches'].items()), flush=True)
        records = [json.loads((output/'cases'/(c['case_id']+'.json')).read_text()) for c in cases]
        manifest['status'] = 'completed' if all(r['comparison']['both_branches_succeeded'] for r in records) else 'completed_with_errors'
        manifest['finished_at'] = utc()
    except (KeyboardInterrupt, SystemExit):
        manifest['status'] = 'interrupted'
        raise
    except Exception:
        manifest['status'] = 'failed'
        raise
    finally:
        manifest['sessions'][-1]['finished_at'] = utc()
        store.write('manifest.json', manifest)
        render_report(output)
    return manifest
