import copy
import json
import tempfile
import unittest
from pathlib import Path
from curator_bench.core import config_from_file, load_benchmark, jev_request, parse_nouls, curate, validate_config
from curator_bench.runtime import run

ROOT = Path(__file__).resolve().parents[1]

class NoulTests(unittest.TestCase):
    def test_contract_selection_and_validation(self):
        config = config_from_file(ROOT/'configs/example.json')
        validate_config(config, offline=True)
        _, cases = load_benchmark(ROOT/'benchmarks/wildchat.json')
        case = cases[0]
        ids = case['source']['history_message_ids']
        request = jev_request(case, config)
        for mid, q in request['questions'].items():
            self.assertEqual(q['type'], 'noul')
            self.assertNotIn('criteria', q)
            self.assertIn("Does this message help determine what the answer should contain, what the request means, or what an acceptable answer must satisfy?", q['instructions'])
            self.assertIn(mid, q['instructions'])
        response = {'answers': {mid: {'type':'noul', 'noul': .1} for mid in ids}}
        response['answers'][ids[0]]['noul'] = .5
        response['answers'][ids[-1]]['noul'] = .99
        parsed = parse_nouls(response, ids)
        result = curate(case, parsed, config['curation'])
        self.assertEqual(result['selected_message_ids'], [ids[0], ids[-1]])
        self.assertEqual(result['history_messages'], [case['input']['history_messages'][0], case['input']['history_messages'][-1]])
        self.assertNotIn('scores', result)
        for bad in (True, '0.8', -1, 1.01, float('nan'), None):
            broken = copy.deepcopy(response)
            broken['answers'][ids[0]]['noul'] = bad
            with self.assertRaises(ValueError): parse_nouls(broken, ids)
        del response['answers'][ids[0]]
        with self.assertRaises(ValueError): parse_nouls(response, ids)

    def test_offline_run_and_report(self):
        config = config_from_file(ROOT/'configs/example.json')
        benchmark, cases = load_benchmark(ROOT/'benchmarks/wildchat.json')
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'noul'
            result = run(config, benchmark, cases[:1], out, offline=True)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['decision_type'], 'noul')
            record = json.loads(next((out/'cases').glob('*.json')).read_text())
            self.assertIn('decisions', record['branches']['with_jev']['curation'])
            self.assertIn('Not relevant', (out/'review.html').read_text())
