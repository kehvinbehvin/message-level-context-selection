"""Verify released inputs, evidence, pair integrity, and checksums without API access."""
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from curator_bench.core import load_benchmark,NOUL_INSTRUCTION,sha
from curator_bench.tool_messages import message_groups
ROOT=Path(__file__).resolve().parents[1]

def main():
    count=0
    for family in ['wildchat','long-context','tool-use']:
        _,cases=load_benchmark(ROOT/'benchmarks'/(family+'.json'));lookup={c['case_id']:c for c in cases}
        folder=ROOT/'results'/family;m=json.loads((folder/'manifest.json').read_text())
        assert m.get('score_instruction',m.get('selection_instruction'))==NOUL_INSTRUCTION
        assert m['config']['curation']=={'mode':'omit_only','order':'chronological','decision_type':'noul','min_probability':.5}
        assert len(m['case_ids'])==len(set(m['case_ids']))
        for cid in m['case_ids']:
            r=json.loads((folder/'cases'/(cid+'.json')).read_text());case=lookup[cid]
            assert r['original_history_messages']==case['input']['history_messages'],cid
            assert r['target_user_message']==case['input']['target_user_message'],cid
            assert r['released_benchmark_input_sha256']==sha(case['input'])
            for name,b in r['branches'].items():
                assert b['status']=='succeeded';request=b['completion']['request'];messages=request['messages']
                assert messages[-1]==case['input']['target_user_message'];assert 'tools' not in request
                message_groups(messages[1:-1])
                history=case['input']['history_messages'] if name=='without_jev' else b['curation']['history_messages']
                assert messages[1:-1]==history
                if name=='with_jev':
                    selection=b['curation'];ids=case['source']['history_message_ids'];kept=selection['selected_message_ids'];assert kept==[mid for mid in ids if mid in kept]
                    assert history==[msg for mid,msg in zip(ids,case['input']['history_messages']) if mid in kept]
                    assert set(selection['decisions'])==set(ids)
                    stage=b.get('jev',{});chunks=stage.get('chunks')
                    stages=list(chunks.values()) if chunks else [stage]
                    seen=[]
                    for st in stages:
                        if not st:continue
                        req=st['request'];assert req['state']['target_user_message']==case['input']['target_user_message']
                        for entry in req['state']['history']:
                            mid=entry['id'];seen.append(mid);assert {k:v for k,v in entry.items() if k!='id'}==case['input']['history_messages'][ids.index(mid)]
                            assert req['questions'][mid]=={'type':'noul','instructions':NOUL_INSTRUCTION.format(message_id=mid)}
                    assert seen==ids
            count+=1
    checks=json.loads((ROOT/'checksums.json').read_text())
    for path,expected in checks.items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==expected,path
    print(f'Verified 34 benchmark cases, {count} paired live records, current prompt, original ordering, targets, tool pairs, and {len(checks)} checksums.')
if __name__=='__main__':main()
