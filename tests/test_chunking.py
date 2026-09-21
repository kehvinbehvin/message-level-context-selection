import copy
import unittest
from curator_bench.core import DEFAULTS, NOUL_INSTRUCTION, aggregate_usage, curate, usage
from curator_bench.chunking import plan_chunks
from curator_bench.runtime import OfflineTransport, execute_branch
from curator_bench.costs import branch_cost


class ChunkTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(DEFAULTS)
        self.config['chunking'] = {'state_question_byte_budget': 3000, 'request_byte_budget': 5000}
        self.case = {'input': {'history_messages': [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': ('hello 世界 ' * 35) + str(i)} for i in range(12)], 'target_user_message': {'role': 'user', 'content': 'What changed?'}}, 'source': {'history_message_ids': [f'm{i:04}' for i in range(12)]}}

    def test_coverage_budgets_and_unchanged_prompt(self):
        chunks = plan_chunks(self.case, self.config)
        self.assertGreater(len(chunks), 1)
        self.assertEqual([mid for ch in chunks for mid in ch['message_ids']], self.case['source']['history_message_ids'])
        rebuilt=[]
        for ch in chunks:
            self.assertLessEqual(ch['size']['state_plus_longest_question_bytes'], 3000)
            self.assertLessEqual(ch['size']['request_bytes'], 5000)
            self.assertEqual(ch['request']['state']['target_user_message'], self.case['input']['target_user_message'])
            for mid,q in ch['request']['questions'].items(): self.assertEqual(q['instructions'], NOUL_INSTRUCTION.format(message_id=mid))
            rebuilt.extend({k:v for k,v in m.items() if k != 'id'} for m in ch['request']['state']['history'])
        self.assertEqual(rebuilt, self.case['input']['history_messages'])

    def test_question_budget_limits_many_short_messages(self):
        self.config['chunking'] = {'state_question_byte_budget':28000, 'request_byte_budget':2200}
        for m in self.case['input']['history_messages']: m['content']='hi'
        chunks=plan_chunks(self.case,self.config)
        self.assertGreater(len(chunks),1)
        self.assertTrue(all(c['size']['request_bytes']<=2200 for c in chunks))

    def test_oversized_message_and_target_fail_before_calls(self):
        for target in (False,True):
            case=copy.deepcopy(self.case)
            if target: case['input']['target_user_message']['content']='x'*6000
            else: case['input']['history_messages'][-1]['content']='x'*6000
            class NoCalls:
                def post(self,*args): raise AssertionError('Must preflight all chunks')
            record={'branches':{}}
            execute_branch('with_jev',case,self.config,NoCalls(),record,lambda:None)
            self.assertEqual(record['branches']['with_jev']['status'],'failed')
            self.assertNotIn('completion',record['branches']['with_jev'])
            self.assertNotIn('jev',record['branches']['with_jev'])

    def test_multi_chunk_usage_selection_and_cost(self):
        record={'branches':{}}
        execute_branch('with_jev',self.case,self.config,OfflineTransport(),record,lambda:None)
        b=record['branches']['with_jev'];stage=b['jev']
        self.assertEqual(b['status'],'succeeded')
        self.assertEqual(len(stage['chunks']),b['chunk_plan']['chunk_count'])
        attempts=[a for c in stage['chunks'].values() for a in c['attempts']]
        self.assertEqual(stage['usage']['input_tokens'],sum(a['usage']['input_tokens'] for a in attempts))
        self.assertEqual(b['usage']['input_tokens'],stage['usage']['input_tokens']+b['completion']['usage']['input_tokens'])
        self.assertAlmostEqual(branch_cost(b,'with_jev')['jev'],stage['usage']['input_tokens']*.042/1e6)
        self.assertFalse(b['curation']['order_changed'])
        self.assertEqual(b['completion']['request']['messages'][1:-1],b['curation']['history_messages'])

    def test_later_chunk_failure_blocks_completion(self):
        class FailSecond(OfflineTransport):
            calls=0
            def post(self,service,*args):
                self.calls+=1
                if self.calls==2: return {'http_status':400,'response':{},'retryable':False}
                return super().post(service,*args)
        transport=FailSecond();record={'branches':{}}
        execute_branch('with_jev',self.case,self.config,transport,record,lambda:None)
        b=record['branches']['with_jev']
        self.assertEqual(transport.calls,2)
        self.assertEqual(b['status'],'failed')
        self.assertNotIn('completion',b)
        self.assertIsNone(b['usage']['input_tokens'])

    def test_interruption_persists_inflight_chunk(self):
        class InterruptSecond(OfflineTransport):
            calls=0
            def post(self,service,*args):
                self.calls+=1
                if self.calls==2: raise KeyboardInterrupt()
                return super().post(service,*args)
        record={'branches':{}};snapshots=[]
        with self.assertRaises(KeyboardInterrupt):
            execute_branch('with_jev',self.case,self.config,InterruptSecond(),record,lambda:snapshots.append(copy.deepcopy(record)))
        saved=snapshots[-1]['branches']['with_jev']['jev']
        self.assertEqual(saved['attempts'][-1]['status'],'in_flight')
        self.assertEqual(saved['chunks']['chunk_0001']['status'],'succeeded')
        self.assertIsNone(aggregate_usage([saved])['input_tokens'])

    def test_empty_history(self):
        self.case['input']['history_messages']=[];self.case['source']['history_message_ids']=[]
        self.assertEqual(plan_chunks(self.case,self.config),[])
