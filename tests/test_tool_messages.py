import copy
import unittest
from curator_bench.core import DEFAULTS,curate,completion_request
from curator_bench.chunking import plan_chunks
from curator_bench.tool_messages import message_groups

class ToolTests(unittest.TestCase):
    def setUp(self):
        self.h=[{'role':'user','content':'Inspect'}, {'role':'assistant','content':'','tool_calls':[{'id':'c1','type':'function','function':{'name':'exec','arguments':'{"input":"ls"}'}},{'id':'c2','type':'function','function':{'name':'exec','arguments':'{"input":"pwd"}'}}]}, {'role':'tool','content':'a.txt','tool_call_id':'c1'},{'role':'tool','content':'/project','tool_call_id':'c2'}]
        self.c={'input':{'history_messages':self.h,'target_user_message':{'role':'user','content':'What files?'}},'source':{'history_message_ids':['m0001','m0002','m0003','m0004']}}
        self.config=copy.deepcopy(DEFAULTS);self.config['curation'].update(decision_type='noul',min_probability=.5)
    def test_group_closure(self):
        for keeper in ['m0002','m0003','m0004']:
            scores={i:{'noul':.9 if i==keeper else .1} for i in self.c['source']['history_message_ids']}
            result=curate(self.c,scores,self.config['curation'])
            self.assertEqual(result['selected_message_ids'],['m0002','m0003','m0004'])
            self.assertEqual(len(result['dependency_retained_message_ids']),2)
            message_groups(result['history_messages'])
    def test_all_dropped(self):
        result=curate(self.c,{i:{'noul':.1} for i in self.c['source']['history_message_ids']},self.config['curation'])
        self.assertEqual(result['history_messages'],[])
    def test_invalid_protocol(self):
        for h in [self.h[:-1],self.h[2:],self.h+[self.h[-1]],self.h[:2]+[self.h[0]]+self.h[2:]]:
            with self.assertRaises(ValueError):message_groups(h)
    def test_chunks_and_completion_preserve_fields(self):
        chunks=plan_chunks(self.c,self.config)
        for ch in chunks:message_groups([{k:v for k,v in m.items() if k!='id'} for m in ch['request']['state']['history']])
        req=completion_request(self.c,self.h,self.config)
        self.assertEqual(req['messages'][1:-1],self.h)
        self.assertNotIn('tools',req)
    def test_oversized_group_fails(self):
        self.config['chunking']={'state_question_byte_budget':100,'request_byte_budget':200}
        with self.assertRaises(ValueError):plan_chunks(self.c,self.config)
