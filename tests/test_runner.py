import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from curator_bench.core import (DEFAULTS, aggregate_usage, completion_request, config_from_file, curate,
                                jev_request, load_benchmark, parse_nouls, sha, validate_config)
from curator_bench.runtime import OfflineTransport, Store, execute_stage, run
from curator_bench.report import render_report

ROOT = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.config = config_from_file(ROOT/'configs/example.json')
        self.benchmark, self.cases = load_benchmark(ROOT/'benchmarks/wildchat.json')
        self.case = self.cases[0]

    def scores(self, case=None, value=.75):
        return {mid: {'type': 'noul', 'noul': value}
                for mid in (case or self.case)['source']['history_message_ids']}

    def test_all_20_inputs_valid(self):
        self.assertEqual(len(self.cases), 20)
        self.assertEqual(len({c['category_id'] for c in self.cases}), 10)
        validate_config(self.config, offline=True)
        with self.assertRaises(ValueError):
            validate_config(self.config, offline=False)

    def test_prompt_isolation_and_identical_targets(self):
        case = copy.deepcopy(self.case)
        case['evaluation_only']['reference_answer'] = 'GOLD_SENTINEL_DO_NOT_SEND'
        case['title'] = 'TITLE_SENTINEL_DO_NOT_SEND'
        request = jev_request(case, self.config)
        plain = json.dumps(request)
        self.assertNotIn('GOLD_SENTINEL', plain)
        self.assertNotIn('TITLE_SENTINEL', plain)
        for mid in case['source']['history_message_ids']:
            self.assertIn(mid, request['questions'][mid]['instructions'])
        baseline = completion_request(case, case['input']['history_messages'], self.config)
        curated = curate(case, self.scores(), self.config['curation'])
        second = completion_request(case, curated['history_messages'], self.config)
        self.assertEqual(baseline['messages'][-1], second['messages'][-1])
        self.assertEqual(baseline['messages'][0], second['messages'][0])
        self.assertEqual(set(request), {'model', 'state', 'questions'})

    def test_stable_fractional_scores_threshold_and_original_content(self):
        scores = self.scores(value=.1)
        ids = self.case['source']['history_message_ids']
        scores[ids[0]]['noul'] = .51
        scores[ids[1]]['noul'] = .52
        scores[ids[2]]['noul'] = .52
        result = curate(self.case, scores, self.config['curation'])
        self.assertEqual(result['selected_message_ids'], [ids[0], ids[1], ids[2]])
        self.assertEqual(result['history_messages'][0], self.case['input']['history_messages'][0])
        self.assertEqual(self.case['input']['history_messages'][0]['content'], result['history_messages'][0]['content'])

    def test_modes_and_empty_selection(self):
        ids = self.case['source']['history_message_ids']
        s = self.scores(value=0)
        self.assertEqual(curate(self.case, s, self.config['curation'])['history_messages'], [])
        s[ids[-1]]['noul'] = 1
        self.assertEqual(curate(self.case, s, self.config['curation'])['selected_message_ids'], [ids[-1]])
        for mode, order in [('reorder_only', 'score_desc'), ('omit_and_reorder', 'score_asc'), ('omit_only', 'score_desc')]:
            config = copy.deepcopy(self.config)
            config['curation'].update(mode=mode, order=order)
            with self.assertRaises(ValueError):
                validate_config(config, offline=True)
            with self.assertRaises(ValueError):
                curate(self.case, s, config['curation'])

    def test_malformed_scores_fail_closed(self):
        ids = self.case['source']['history_message_ids']
        good = {'answers': {i: s for i,s in self.scores().items()}}
        self.assertEqual(set(parse_nouls(good, ids)), set(ids))
        for value in [float('nan'), float('inf'), -1, 5, True, '2']:
            bad = copy.deepcopy(good); bad['answers'][ids[0]]['noul'] = value
            with self.assertRaises(ValueError):
                parse_nouls(bad, ids)
        for change in ['missing', 'extra']:
            bad = copy.deepcopy(good)
            if change == 'missing':bad['answers'].pop(ids[0])
            else:bad['answers']['invented'] = {'type': 'noul', 'noul': 1}
            with self.assertRaises(ValueError):parse_nouls(bad, ids)

    def test_unknown_usage_is_not_zero(self):
        result = aggregate_usage([{'attempts': [{'usage': {'input_tokens': 10, 'output_tokens': 2}}, {'usage': {'input_tokens': None, 'output_tokens': None}}]}])
        self.assertIsNone(result['input_tokens'])
        self.assertEqual(result['observed_input_tokens'], 10)
        self.assertFalse(result['input_tokens_complete'])

    def test_invalid_benchmark_and_reserved_parameters(self):
        bad = copy.deepcopy(self.benchmark)
        bad['cases'][0]['input']['history_messages'][0]['content'] = 'mutated'
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'bad.json'; p.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):load_benchmark(p)
        for key in ['messages', 'stream', 'n', 'tools', 'model']:
            config = copy.deepcopy(self.config); config['completion_parameters'][key] = 'bad'
            with self.assertRaises(ValueError):validate_config(config, offline=True)

    def test_offline_run_no_network_and_resume_no_replay(self):
        with tempfile.TemporaryDirectory() as tmp, patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Network forbidden')):
            output = Path(tmp)/'demo'
            manifest = run(self.config, self.benchmark, self.cases[:2], output, offline=True)
            self.assertEqual(manifest['status'], 'completed')
            first = json.loads((output/'cases'/(self.cases[0]['case_id']+'.json')).read_text())
            second = json.loads((output/'cases'/(self.cases[1]['case_id']+'.json')).read_text())
            self.assertEqual(first['branch_order'], ['without_jev', 'with_jev'])
            self.assertEqual(second['branch_order'], ['with_jev', 'without_jev'])
            self.assertEqual(first['usage']['attempt_count'], 3)
            for name,b in first['branches'].items():
                self.assertGreaterEqual(b['duration_seconds'], b['completion']['duration_seconds'])
                self.assertEqual(b['completion']['request']['messages'][-1], self.case['input']['target_user_message'])
            self.assertIn('OFFLINE FIXTURE RUN', (output/'review.html').read_text())
            before = (output/'cases'/(self.case['case_id']+'.json')).read_bytes()
            class NeverCall:
                def post(self, *a):raise AssertionError('Completed branches must not replay')
            run(self.config, self.benchmark, self.cases[:2], output, offline=True, resume=True, transport=NeverCall())
            after = json.loads((output/'cases'/(self.case['case_id']+'.json')).read_text())
            self.assertEqual(json.loads(before)['branches'], after['branches'])
            changed = copy.deepcopy(self.config); changed['curation']['min_probability'] = .8
            with self.assertRaises(ValueError):run(changed, self.benchmark, self.cases[:2], output, offline=True, resume=True)

    def test_failed_jev_never_uses_baseline_fallback(self):
        calls = []
        class BadJev(OfflineTransport):
            def post(self, service, *args):
                calls.append(service)
                if service == 'jev':return {'http_status': 200, 'response': {'answers': {}}, 'retryable': False}
                return super().post(service, *args)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'failed'
            run(self.config, self.benchmark, self.cases[:1], output, offline=True, transport=BadJev())
            r=json.loads((output/'cases'/(self.case['case_id']+'.json')).read_text())
            self.assertEqual(calls, ['openai', 'jev'])
            self.assertEqual(r['branches']['with_jev']['status'], 'failed')
            self.assertNotIn('completion', r['branches']['with_jev'])
            self.assertIsNone(r['branches']['with_jev']['usage']['input_tokens'])

    def test_retry_accounting_and_delay(self):
        count = []
        class RetryTransport:
            def post(self, *args):
                count.append(1)
                if len(count)==1:return {'http_status': 429, 'response': {}, 'retryable': True, 'transport_error': 'HTTP request failed'}
                return {'http_status': 200, 'response': {'usage': {'input_tokens': 8, 'output_tokens': 2}}, 'retryable': False}
        config = dict(self.config, max_retries=1)
        with patch('curator_bench.runtime.time.sleep') as sleep:
            result = execute_stage('jev', 'unused', {}, config, RetryTransport(), {}, 'jev', lambda:None, lambda r:r)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(len(result['attempts']), 2)
        self.assertIsNone(result['usage']['input_tokens'])
        self.assertEqual(result['usage']['observed_input_tokens'], 8)
        sleep.assert_called_once_with(1)

    def test_interrupt_saved_and_not_replayed(self):
        class Interrupt(OfflineTransport):
            def post(self, *args):raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'interrupt'
            with self.assertRaises(KeyboardInterrupt):
                run(self.config, self.benchmark, self.cases[:1], output, offline=True, transport=Interrupt())
            path=output/'cases'/(self.case['case_id']+'.json')
            r=json.loads(path.read_text())
            self.assertEqual(r['branches']['without_jev']['completion']['attempts'][0]['status'], 'in_flight')
            result=run(self.config, self.benchmark, self.cases[:1], output, offline=True, resume=True)
            r=json.loads(path.read_text())
            self.assertEqual(r['branches']['without_jev']['status'], 'interrupted')
            self.assertEqual(r['branches']['with_jev']['status'], 'succeeded')
            self.assertIsNone(r['usage']['input_tokens'])
            self.assertEqual(result['status'], 'completed_with_errors')

    def test_report_escapes_untrusted_text_and_secret_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp, ['test-secret-value'])
            store.write('test.json', {'error':'server echoed test-secret-value'})
            self.assertNotIn('test-secret-value',(Path(tmp)/'test.json').read_text())
            output=Path(tmp)/'report'
            run(self.config,self.benchmark,self.cases[:1],output,offline=True)
            path=output/'cases'/(self.case['case_id']+'.json');r=json.loads(path.read_text())
            r['branches']['without_jev']['answer']['text']='<script>BAD_SENTINEL</script>'
            path.write_text(json.dumps(r));render_report(output)
            doc=(output/'review.html').read_text()
            self.assertNotIn('<script>BAD_SENTINEL</script>',doc)
            self.assertIn('&lt;script&gt;BAD_SENTINEL&lt;/script&gt;',doc)

    def test_existing_run_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError):run(self.config,self.benchmark,self.cases[:1],Path(tmp),offline=True)

    def test_http_contract_and_error_response(self):
        import io
        import urllib.error
        from unittest.mock import Mock
        from curator_bench.runtime import HTTPTransport, decode_body
        class Response:
            status = 200
            headers = {'x-request-id': 'request-fixture'}
            def __enter__(self):return self
            def __exit__(self, *args):pass
            def read(self):return b'{"choices":[],"usage":{"prompt_tokens":7}}'
        transport = HTTPTransport('fake-openai-secret', 'fake-jev-secret')
        transport.opener = Mock()
        transport.opener.open.return_value = Response()
        body = {'model': 'model-fixture', 'messages': [{'role': 'user', 'content': 'hello'}]}
        result = transport.post('openai', 'https://example.invalid/v1/chat/completions', body, 10)
        request = transport.opener.open.call_args.args[0]
        self.assertEqual(request.method, 'POST')
        self.assertEqual(json.loads(request.data), body)
        self.assertEqual(request.get_header('Authorization'), 'Bearer fake-openai-secret')
        self.assertEqual(result['request_id'], 'request-fixture')
        self.assertNotIn('fake-openai-secret', json.dumps(result))
        transport.opener.open.side_effect = urllib.error.HTTPError('https://example.invalid', 429, 'rate limit', {}, io.BytesIO(b'{"error":{"message":"slow down"}}'))
        result = transport.post('jev', 'https://example.invalid/v1/systemone', {}, 10)
        self.assertEqual(result['http_status'], 429)
        self.assertTrue(result['retryable'])
        self.assertEqual(result['response']['error']['message'], 'slow down')
        self.assertIsNone(decode_body(b'{"score": NaN}')[0])

    def test_refusal_and_truncation_preserved_without_retry(self):
        from curator_bench.core import completion_answer
        refusal = completion_answer({'choices':[{'message':{'content':None,'refusal':'Declined'},'finish_reason':'stop'}]})
        self.assertEqual(refusal['text'], 'Declined')
        answer = completion_answer({'choices':[{'message':{'content':'partial'},'finish_reason':'length'}]})
        self.assertTrue(answer['truncated'])
        with self.assertRaises(ValueError):completion_answer({'choices':[{'message':[]} ]})
        with self.assertRaises(ValueError):completion_answer({'choices':[{'message':{'content':None,'tool_calls':[{}]}}]})

    def test_live_requires_both_keys_before_request(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ',{},clear=True):
            output=Path(tmp)/'missing'
            with self.assertRaises(ValueError):run(self.config,self.benchmark,self.cases[:1],output,offline=False)
            self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
