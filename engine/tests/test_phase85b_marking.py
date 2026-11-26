from __future__ import annotations

import copy
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from engine.src.memo_engine.marking_interpretation import interpret_marking, marking_schema
from engine.src.memo_engine.mathematical_consistency import check_expression
from engine.src.memo_engine.semantic import build_semantic_plan, interpret_semantics
from engine.src.memo_engine.visual_evidence import fuse_visual_evidence
from engine.src.memo_engine.canonical import build_canonical_memo


def fixture():
    text='MATHEMATICS PAPER 1 CLASS TEST 2026\nFORM 5 TIME: 1 HOUR\nQUESTION 1\n1.1 Calculate the sum. (2)\nTOTAL: 2'
    q={'question_id':'1.1','source_question_id':'1.1','path':[1,1],'depth':2,'context_only':False,
       'source_block_index':0,'source_character_offset':text.index('1.1'),'source_page':1,
       'printed_marks':None,'mark_points':[],'source_preview':'1.1 Calculate the sum. (2)'}
    normalized={'job_id':'synthetic-bridge','source':{'sha256':'synthetic','detected_kind':'pdf'},
                'content':{'kind':'pdf','pages':[{'page':1,'effective_text':text}]}}
    observations=[]
    for i,(kind,transcription) in enumerate([('answer_working','2+3=5'),('marking_note','1M method'),('marking_note','1A final answer')]):
        observations.append({'evidence_id':f'e{i}','kind':kind,'transcription':transcription,
            'normalized_math':'2+3=5' if i==0 else None,'confidence':.98,'effective':True,'question_ref':'1.1',
            'owned_question_ref':'1.1','page':1,'association_status':'owned','source_page_bbox':[20,100+i*20,200,115+i*20],
            'rendered_asset_ref':'internal/visual/synthetic.png'})
    return {'job_id':'synthetic-bridge','questions':[q],'subtotals':[],'exceptions':[]},normalized,{'evidence':observations,'mark_changes':[],'assets':[]}


def criterion(category='proposed',count=1,code='A',quote='',allocation=None,steps=None):
    return {'category':category,'count':count,'code':code,'descriptor':'final answer','allocation_quote':quote,
            'allocation_evidence_ids':allocation or [],'solution_evidence_ids':steps or ['e0'],'alternative':0}


def responder(criteria,roles=None,notes=None):
    return lambda _packet:SimpleNamespace(value={'roles':roles or [],'criteria':criteria,'notes':notes or []},
        model='gpt-6-luna',usage={},elapsed_ms=1,quota={})


def test_explicit_handwritten_instructions_populate_marks_and_source_step_references():
    s,n,v=fixture();fuse_visual_evidence(s,v)
    result,a=interpret_marking(s,n,v)
    assert a['summary']['source_backed_marking_points']==2
    assert result['questions'][0]['printed_marks']==2
    assert len(build_semantic_plan(result)[0])==2
    assert all(p['source_refs']==[{'file_id':'source_1','page':1}] and p['solution_evidence_ids']==['e0'] for p in result['questions'][0]['mark_points'])


@pytest.mark.parametrize('category',['explicit','ambiguous','proposed'])
def test_ticks_and_printed_totals_cannot_manufacture_accepted_allocations(category):
    s,n,v=fixture();v['evidence']=v['evidence'][:1]+[{**v['evidence'][1],'kind':'tick','transcription':'checkmark'}]
    p=criterion(category,quote='checkmark',allocation=['e1'])
    result,a=interpret_marking(s,n,v,interpreter=responder([p]))
    assert result['questions'][0]['mark_points']==[]
    assert a['summary']['unconfirmed_criteria']==1
    assert any(e['category']=='marking_interpretation_review' for e in result['exceptions'])


def test_deduction_and_ca_without_count_stay_unconfirmed_and_reviewable():
    s,n,v=fixture();v['evidence'][1]['transcription']='-1 if no conclusion'
    result,a=interpret_marking(s,n,v,interpreter=responder([
        criterion('explicit',quote='-1 if no conclusion',allocation=['e1'])]))
    assert not result['questions'][0]['mark_points']
    assert a['questions'][0]['unconfirmed'][0]['category']=='ambiguous'
    v['evidence'][1]['transcription']='CA'
    v['evidence']=v['evidence'][:2]
    result,a=interpret_marking(s,n,v)
    assert not result['questions'][0]['mark_points']


def test_proposals_classify_separately_without_becoming_accepted_or_green():
    s,n,v=fixture();v['evidence']=v['evidence'][:1]
    # A deterministic descriptor still cannot turn a draft into an accepted source mark.
    result,a=interpret_marking(s,n,v,interpreter=responder([criterion()]),classifier=lambda *_a,**_k:pytest.fail('deterministic proposal needs no API'))
    assert result['questions'][0]['mark_points']==[]
    assert a['proposal_semantics']['deterministic_results'][0]['band']=='amber'
    assert a['summary']['proposal_semantic_candidates']==1


def test_no_double_counting_and_typed_marking_points_preserved():
    s,n,v=fixture();p=criterion('explicit',quote='1A final answer',allocation=['e2'])
    result,a=interpret_marking(s,n,v,interpreter=responder([p,p]))
    assert len(result['questions'][0]['mark_points'])==1
    typed=copy.deepcopy(s);typed['questions'][0]['mark_points']=[{'count':2,'code':'A','descriptor':'typed answer'}]
    out,a=interpret_marking(typed,n,v,interpreter=lambda _:pytest.fail('typed marks must not be reinterpreted'))
    assert out==typed


def test_unknown_source_ids_or_approval_as_working_fail_closed():
    s,n,v=fixture()
    with pytest.raises(ValueError):interpret_marking(s,n,v,interpreter=responder([criterion(steps=['absent'])]))
    result,a=interpret_marking(s,n,v,interpreter=responder([criterion(steps=['e1'])]))
    assert not result['questions'][0]['mark_points']
    assert a['questions'][0]['unconfirmed'][0]['category']=='ambiguous'


def test_alternative_allocations_use_maximum_and_never_sum_or_duplicate_typed_methods():
    s,n,v=fixture();p=criterion('explicit',quote='1A final answer',allocation=['e2'])
    other={**p,'alternative':1}
    result,a=interpret_marking(s,n,v,interpreter=responder([p,other]))
    assert len(result['questions'][0]['mark_points'])==2
    assert result['questions'][0]['computed_shorthand_marks']==1
    assert result['questions'][0]['mark_calculation_mode']=='alternative_max'


def test_source_occurrence_and_structural_parent_are_preserved():
    s,n,v=fixture();parent={**s['questions'][0],'question_id':'1','context_only':True}
    s['questions'].insert(0,parent)
    result,a=interpret_marking(s,n,v)
    assert result['questions'][0]==parent
    duplicate=copy.deepcopy(s['questions'][1]);duplicate['source_page']=2;s['questions'].append(duplicate)
    result,a=interpret_marking(s,n,v)
    assert result['questions'][1]['mark_points']==[] # a duplicate label needs placement review


@pytest.mark.parametrize('expression,status',[
    (r'\frac{6!\times 2}{2!\,2!}=180','checked_fail'),
    (r'\frac{4!\times 2}{2!\,2!}=12','checked_pass'),
    ('2!!=2','not_checked'),('21!=1','not_checked'),('sin(2)=1','not_checked'),('2 3=23','not_checked')])
def test_narrow_factorial_products_and_unsupported_notation(expression,status):
    result,_=check_expression(expression)
    assert result['status']==status
    if '6!' in expression:assert result['relations'][0]['left_value']=='360'


def test_end_to_end_handwritten_memo_reaches_legitimate_rendering_eligibility():
    s,n,v=fixture()
    # Controlled handwritten source fixture, rather than a typed marking-column input.
    import fitz
    image=Image.new('RGB',(600,160),'white');draw=ImageDraw.Draw(image)
    for y,line in [(15,'2+3=5'),(60,'1M method'),(105,'1A final answer')]:draw.text((30,y),line,fill='blue')
    png=io.BytesIO();image.save(png,format='PNG')
    pdf=fitz.open();page=pdf.new_page();page.insert_text((40,60),n['content']['pages'][0]['effective_text'])
    page.insert_image(fitz.Rect(40,180,500,300),stream=png.getvalue());source=pdf.tobytes();pdf.close()
    fuse_visual_evidence(s,v)
    result,a=interpret_marking(s,n,v)
    semantic=interpret_semantics(result)
    canonical,validation,_=build_canonical_memo(
        {'id':'synthetic-bridge','source_filename':'handwritten.pdf','source_mime':'application/pdf'},
        {'source':{'sha256':'synthetic','detected_kind':'pdf','detected_mime':'application/pdf','size_bytes':len(source)}},
        n,result,semantic,source)
    assert canonical['totals']['computed']==2
    assert validation['mathematical_consistency']['checked_expression_count']>=1
    assert validation['handoff_ready'] and canonical['status']=='render_ready'
    marks=canonical['questions'][0]['items'][0]['alternatives'][0]['marking_points']
    assert all(p['applies_to_block_ids'] and p['source_marking']['solution_evidence_ids']==['e0'] for p in marks)


def test_cross_page_visual_evidence_attaches_only_to_its_own_occurrence():
    s,n,v=fixture();other=copy.deepcopy(s['questions'][0]);other['source_page']=2;s['questions'].append(other)
    fuse_visual_evidence(s,v)
    assert s['questions'][0]['visual_evidence']
    assert not s['questions'][1].get('visual_evidence')


def test_unknown_tick_allocation_stays_unspecified_and_not_semantically_accepted():
    s,n,v=fixture();p=criterion('ambiguous',count=None,quote='checkmark',allocation=['e1'])
    result,a=interpret_marking(s,n,v,interpreter=responder([p]))
    assert a['questions'][0]['unconfirmed'][0]['count'] is None
    assert not result['questions'][0]['mark_points']


def test_question_packet_cache_does_not_repeat_inference():
    s,n,v=fixture()
    result,a=interpret_marking(s,n,v,interpreter=responder([criterion()]))
    result,b=interpret_marking(s,n,v,cached=a,interpreter=lambda _:pytest.fail('cached packet repeated'))
    assert b['summary']['interpretation_calls']==0 and b['questions'][0]['cache_hit']


@pytest.mark.parametrize('defect',[None,'wrong_state','wrong_history','already_published','teacher_correction','claim_race','late_correction'])
def test_distinct_marking_lifecycle_preserves_coordinate_history_and_archives_before_claim(monkeypatch,defect):
    import hashlib
    from engine.src.memo_engine import marking_revalidation as module,cli
    from engine.src.memo_engine.openai_credit import PBHS_URL,PILOT_JOB
    source=b'x'*1_007_519;sha=hashlib.sha256(source).hexdigest()
    monkeypatch.setattr(cli,'PHASE85_SOURCE_SHA256',sha)
    for key,value in {'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'PBHSVVI/PBHS_MEMO_CONVERTER',
                      'GITHUB_REF':'refs/heads/main','GITHUB_WORKFLOW':'Process Memo',
                      'GITHUB_RUN_ID':'456','GITHUB_RUN_ATTEMPT':'1'}.items():monkeypatch.setenv(key,value)
    old={'job_id':PILOT_JOB,'coordinate_revalidation':{'contract':'original-contract'}}
    if defect=='wrong_history':old.pop('coordinate_revalidation')
    if defect=='already_published':old['marking_revalidation']={'version':'previous'}
    trace=[]
    class DB:
        base=PBHS_URL
        def __init__(self):
            self.job={'id':PILOT_JOB,'user_id':'owner','status':'needs_review','stage':'phase5_canonicalized',
                      'source_sha256':sha,'updated_at':'2026-11-26T09:41:00Z','attempt_count':5,
                      'source_path':f'owner/{PILOT_JOB}/source/memo.pdf'}
            if defect=='wrong_state':self.job['status']='complete'
            self.claimed=False
        def get_job(self,_):return dict(self.job)
        def _request_json(self,method,path,**kwargs):
            if method=='PATCH':
                assert len([x for x in trace if x=='archive'])==9
                assert 'updated_at=eq.' in path
                if defect=='claim_race':return []
                self.job.update(kwargs['body']);self.claimed=True;return [dict(self.job)]
            assert method=='GET'
            if '/corrections?' in path and (defect=='teacher_correction' or self.claimed and defect=='late_correction'):return [{'id':'real'}]
            return []
        def download_object(self,_,path):
            if '/source/' in path:return source
            if path.endswith('/visual/evidence.json'):return json.dumps(old).encode()
            return b'{}'
        def download_json(self,*_):return None
        def upload_object(self,_,path,data,**kw):
            assert '/revisions/phase85b-456-1/' in path and not kw['upsert'];trace.append('archive')
        def upload_json(self,_,path,value,**kw):
            assert '/revisions/phase85b-456-1/' in path and not kw['upsert'];trace.append('archive')
        def add_event(self,job,event,*_):trace.append(event)
        def patch_job(self,_,expected,values):self.job.update(values);return self.job
    def refresh(visual,*_a,**_k):
        assert visual['coordinate_revalidation']=={'contract':'original-contract'}
        trace.append('recognition');return {**visual,'marking_revalidation':{'version':'new'}}
    def worker(job,**kwargs):
        assert kwargs['replay_visual']['coordinate_revalidation']==old['coordinate_revalidation']
        trace.append('worker');return 0
    monkeypatch.setattr(module,'refresh_readings',refresh)
    monkeypatch.setattr(module,'OpenAIInterpreter',lambda *_a,**_k:object())
    monkeypatch.setattr(cli,'run_job',worker)
    db=DB()
    if defect is None:
        assert module.revalidate_marking(PILOT_JOB,db)==0
        assert trace.index('marking_revalidation_started')<trace.index('recognition')<trace.index('worker')
        assert trace[-1]=='marking_revalidation_complete'
    else:
        with pytest.raises(ValueError):module.revalidate_marking(PILOT_JOB,db)
        assert 'worker' not in trace and 'recognition' not in trace


def test_teacher_proposal_control_only_prepares_a_local_editable_draft():
    from pathlib import Path
    page=(Path(__file__).resolve().parents[2]/'docs/phase7-5-review/index.html').read_text(encoding='utf8')
    section=page.split("ex.category==='marking_interpretation_review'",1)[1].split("}else if(!grouped&&ex.category==='ambiguous_mark_semantics'",1)[0]
    assert 'Prepare editable marking draft' in section
    assert 'not submitted or confirmed' in section
    assert 'textContent' in section
    assert 'submitAndInterpret' not in section and 'confirmCorrection' not in section
