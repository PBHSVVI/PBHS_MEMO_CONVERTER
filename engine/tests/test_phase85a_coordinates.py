from __future__ import annotations

import copy
import hashlib
import json

import pytest

from engine.src.memo_engine import coordinate_revalidation as replay
from engine.src.memo_engine import visual_evidence as ve
from engine.src.memo_engine.canonical import build_canonical_memo
from engine.src.memo_engine.semantic import interpret_semantics
from engine.src.memo_engine.visual_coordinates import OPENAI_COORDINATE_CONTRACT, openai_crop_pixels


def payload(box=None, *, question="1.1", working="2+3=5", mark_changes=None):
    return {"schema_version": "1.0", "page": 1, "visual_content_present": True, "warnings": [],
            "evidence": [{"question_ref": question, "kind": "answer_working", "transcription": working,
                          "normalized_math": working, "confidence": .97, "source": "visual_overlay",
                          "bbox": box if box is not None else [.1, .25, .8, .5]}],
            "mark_changes": mark_changes or []}


def region(width=1000, height=400):
    return {"page": 1, "asset_path": "internal/visual/regions/synthetic.png", "question_refs": ["1.1"],
            "pixel_width": width, "pixel_height": height, "render_scale": 2,
            "render_bbox": [30., 150., 530., 350.], "owned_bbox": [30., 180., 530., 330.],
            "page_bbox": [0., 0., 600., 800.], "printed_text": "1.1 Calculate the answer. (1)"}


def validated(raw, reg=None):
    reg = reg or region()
    fixed = openai_crop_pixels(raw, reg["pixel_width"], reg["pixel_height"])
    return ve.validate_visual_response({**fixed, "provider": "openai", "model": "gpt-6-luna"}, reg)


@pytest.mark.parametrize("width,height", [(1000,400), (503,1700), (2048,128), (125,125)])
def test_non_origin_crop_dimensions_and_page_transform(width, height):
    raw = payload()
    converted = openai_crop_pixels(raw, width, height)
    assert converted["evidence"][0]["bbox"] == [.1*width, .25*height, .8*width, .5*height]
    observed = validated(raw, region(width, height))["evidence"][0]
    assert observed["source_page_bbox"] == pytest.approx([80, 200, 430, 250])
    assert observed["association_status"] == "owned" and observed["effective"]
    assert observed["provider_bbox"] == raw["evidence"][0]["bbox"]
    assert observed["coordinate_contract"] == OPENAI_COORDINATE_CONTRACT
    assert raw["evidence"][0]["bbox"] == [.1,.25,.8,.5]


@pytest.mark.parametrize("box,question,status", [
    ([.1,.01,.2,.05], "1.1", "context_only"),
    ([.1,.25,.8,.5], "1.2", "cross_anchor_mismatch"),
])
def test_real_margin_and_cross_question_evidence_stay_suppressed(box, question, status):
    item = validated(payload(box, question=question))["evidence"][0]
    assert item["association_status"] == status and item["effective"] is False


@pytest.mark.parametrize("box", [[0,0,10,20], [-.1,0,.5,.5], [.5,0,.2,.5], [0,0,1,0],
                                  [0,0,float('nan'),1], [False,0,1,1], [0,0,1], [0,0,float('inf'),1]])
def test_invalid_declared_unit_coordinates_are_rejected_without_unit_guessing(box):
    with pytest.raises(ValueError):
        openai_crop_pixels(payload(box), 1000, 400)


def test_missing_coordinate_provenance_or_dimensions_cannot_establish_ownership():
    with pytest.raises(ve.VisualEvidenceError):
        ve.validate_visual_response({**payload(), "provider": "openai"}, region())
    for dimensions in [(0,10), (100,False), (100.0,20)]:
        with pytest.raises(ValueError):
            openai_crop_pixels(payload(), *dimensions)
    raw=payload();raw['evidence'][0]['bbox']=None
    assert validated(raw)['evidence'][0]['effective'] is False


def test_mark_change_coordinates_use_the_same_contract_and_checks():
    change={"question_ref":"1.1","level":"item","printed_value":1,"visual_value":2,
            "confidence":.96,"requires_confirmation":True,"bbox":[.1,.3,.2,.4]}
    item=validated(payload(mark_changes=[change]))['mark_changes'][0]
    assert item['effective'] and item['source_page_bbox']==pytest.approx([80,210,130,230])
    assert item['provider_bbox']==change['bbox']
    for defect in ({'question_ref':'1.2'}, {'bbox':[.1,.01,.2,.05]}):
        assert not validated(payload(mark_changes=[{**change,**defect}]))['mark_changes'][0]['effective']


def test_repeated_conversion_is_idempotent_and_tampering_fails_closed():
    once=openai_crop_pixels(payload(),1000,400)
    assert openai_crop_pixels(once,1000,400)==once
    twice=copy.deepcopy(once);twice['evidence'][0]['bbox'][0]*=1000
    with pytest.raises(ValueError):openai_crop_pixels(twice,1000,400)
    with pytest.raises(ValueError):openai_crop_pixels(once,400,1000)
    other=copy.deepcopy(once);other['coordinate_provenance']['source_space']='unknown'
    with pytest.raises(ValueError):openai_crop_pixels(other,1000,400)


def test_groq_and_cloudflare_keep_existing_pixel_coordinate_semantics():
    for provider in ['groq','cloudflare']:
        p=payload([100,100,800,200]);p['provider']=provider
        result=ve.validate_visual_response(p,region())['evidence'][0]
        assert result['source_page_bbox']==[80,200,430,250]
        assert 'provider_bbox' not in result


def test_mixed_checkpoint_replay_preserves_original_runs_and_free_provider_evidence(monkeypatch):
    reg=region();reg['image_bytes']=b'controlled crop'
    digest=hashlib.sha256(reg['image_bytes']).hexdigest();source=b'controlled source'
    legacy=ve.validate_visual_response({**payload(), 'provider':'groq'}, reg)['evidence'][0]
    legacy.update(extractor_provider='openai',extractor_model='gpt-6-luna',effective=False)
    free=copy.deepcopy(legacy);free.update(extractor_provider='cloudflare',rendered_asset_ref='free.png')
    free_reg={**reg,'asset_path':'free.png','image_bytes':b'free crop'}
    def run(r,provider):
        return dict(region_id=r['asset_path'],rendered_asset_ref=r['asset_path'],success=True,
                    provider=provider,model='gpt-6-luna' if provider=='openai' else 'free-model',
                    task_prompt_version='visual-evidence-v1',source_digest=hashlib.sha256(source).hexdigest(),
                    crop_digest=hashlib.sha256(r['image_bytes']).hexdigest(),result_digest=provider+'-original')
    saved=dict(ownership_algorithm_version=ve.OWNERSHIP_ALGORITHM_VERSION,source_sha256=hashlib.sha256(source).hexdigest(),
               evidence=[legacy,free],mark_changes=[],runs=[run(reg,'openai'),run(free_reg,'cloudflare')],
               assets=[dict(path=r['asset_path'],sha256=hashlib.sha256(r['image_bytes']).hexdigest()) for r in [reg,free_reg]],
               summary={})
    monkeypatch.setattr(replay,'_render_regions',lambda *_:[reg,free_reg])
    fixed=replay.rebuild_visual_checkpoint(saved,source,{})
    assert fixed['evidence'][0]['effective']
    assert fixed['evidence'][1]==free and fixed['runs']==saved['runs']
    assert saved['evidence'][0]['effective'] is False
    assert fixed==replay.rebuild_visual_checkpoint(fixed,source,{})
    bad=copy.deepcopy(saved);bad['runs'][0]['crop_digest']='changed'
    with pytest.raises(ValueError):replay.rebuild_visual_checkpoint(bad,source,{})


@pytest.mark.parametrize('working,expected', [('2+3=5','checked_pass'),('2+3=6','checked_fail')])
def test_non_origin_evidence_reaches_fusion_marks_and_math_validation(working,expected):
    result=validated(payload(working=working))
    question={"question_id":"1.1","source_question_id":"1.1","path":[1,1],"depth":2,"context_only":False,
              "source_block_index":0,"source_page":1,"source_character_offset":0,"printed_marks":1,
              "computed_shorthand_marks":1,"mark_calculation_mode":"additive",
              "mark_points":[{"count":1,"code":"A","descriptor":"answer","notation":"shorthand"}],
              "source_preview":"1.1 Calculate the answer. (1)"}
    structure={"job_id":"synthetic-coordinate","questions":[question],"subtotals":[],"exceptions":[]}
    ve.fuse_visual_evidence(structure,{"evidence":result['evidence'],"mark_changes":[],"assets":[]})
    assert structure['summary']['visual_evidence_attached_count']==1
    semantic=interpret_semantics(structure,classifier=lambda *_a,**_k:pytest.fail('deterministic source marks need no API'))
    assert semantic['summary']['mark_points_total']==1
    normalized={"job_id":"synthetic-coordinate","source":{"sha256":"synthetic","detected_kind":"pdf"},
                "content":{"kind":"pdf","pages":[{"page":1,"effective_text":"1.1 Calculate the answer. (1)\nTOTAL: 1"}]}}
    job={"id":"synthetic-coordinate","source_filename":"synthetic.pdf","source_mime":"application/pdf"}
    ingestion={"source":{"sha256":"synthetic","detected_kind":"pdf","detected_mime":"application/pdf","size_bytes":1}}
    canonical,validation,_=build_canonical_memo(job,ingestion,normalized,structure,semantic,b'%PDF-synthetic')
    assert canonical['totals']['computed']==1
    checks=validation['mathematical_consistency']['checks']
    assert any(c['status']==expected for c in checks)
    if expected=='checked_fail':
        assert not validation['handoff_ready']
        assert validation['mathematical_consistency']['conflict_count']>=1


def test_revalidation_rejects_unapproved_project_job_state_and_non_hosted_execution(monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
    class DB:
        base='https://wrong.supabase.co'
    with pytest.raises(ValueError,match='pilot'):replay.revalidate_job('other',DB())
    from engine.src.memo_engine.openai_credit import PILOT_JOB,PBHS_URL
    with pytest.raises(ValueError,match='project'):replay.revalidate_job(PILOT_JOB,DB())
    DB.base=PBHS_URL
    monkeypatch.delenv('GITHUB_RUN_ID')
    with pytest.raises(ValueError,match='hosted'):replay.revalidate_job(PILOT_JOB,DB())


@pytest.mark.parametrize('defect', [None, 'correction', 'archive_failure', 'claim_race', 'late_correction', 'wrong_state'])
def test_audited_claim_archives_before_same_job_replay_and_never_fakes_corrections(monkeypatch, defect):
    from engine.src.memo_engine import cli
    from engine.src.memo_engine.openai_credit import PILOT_JOB, PBHS_URL
    # Keep the production byte-length guard in this test, using a real-sized synthetic fixture.
    source=b'x'*1_007_519;sha=hashlib.sha256(source).hexdigest()
    monkeypatch.setattr(cli,'PHASE85_SOURCE_SHA256',sha)
    monkeypatch.setenv('GITHUB_RUN_ID','789');monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
    for key,value in {'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'PBHSVVI/PBHS_MEMO_CONVERTER',
                      'GITHUB_REF':'refs/heads/main','GITHUB_WORKFLOW':'Process Memo'}.items():
        monkeypatch.setenv(key,value)
    free=[{'region_id':r,'provider':'groq'} for r in cli.PHASE85_SAVED_REGIONS]
    visual={'job_id':PILOT_JOB,'runs':free,'assets':[]}
    rebuilt={'runs':[{}]*21,'coordinate_revalidation':{'recovered_openai_regions':15}}
    monkeypatch.setattr(replay,'rebuild_visual_checkpoint',lambda *_:copy.deepcopy(rebuilt))
    trace=[]
    class DB:
        base=PBHS_URL
        def __init__(self):
            self.job={'id':PILOT_JOB,'user_id':'owner','status':'needs_review','stage':'phase5_canonicalized',
                      'source_sha256':sha,'source_path':f'owner/{PILOT_JOB}/source/memo.pdf',
                      'updated_at':'2026-11-26T09:01:17Z','attempt_count':4}
            if defect=='wrong_state':self.job['status']='complete'
            self.claimed=False
        def get_job(self,_):return dict(self.job)
        def _request_json(self,method,path,**kwargs):
            trace.append((method,path))
            if method=='PATCH':
                assert path.startswith('/rest/v1/jobs?') and 'updated_at=eq.' in path
                assert len([x for x in trace if x[0]=='archive'])==9
                if defect=='claim_race':return []
                self.claimed=True;self.job.update(kwargs['body']);return [dict(self.job)]
            assert method=='GET'
            if '/corrections?' in path and (defect=='correction' or self.claimed and defect=='late_correction'):
                return [{'id':'real-teacher-correction'}]
            return []
        def download_object(self,_,path):
            if '/source/' in path:return source
            if path.endswith('/visual/evidence.json'):return json.dumps(visual).encode()
            if path.endswith('/normalized.json'):return json.dumps({'source':{'sha256':sha}}).encode()
            return b'{"original":true}'
        def upload_object(self,_,path,data,**kwargs):
            assert kwargs['upsert'] is False and '/revisions/phase85a-789-1/' in path
            if defect=='archive_failure':raise RuntimeError('storage unavailable')
            trace.append(('archive',path))
        def upload_json(self,_,path,value,**kwargs):
            assert kwargs['upsert'] is False and value['corrections']==[]
            trace.append(('archive',path))
        def add_event(self,job,event,*args):trace.append(('event',event))
        def patch_job(self,*args):
            assert defect=='late_correction';trace.append(('restore_review',args));return self.job
    def worker(job_id,**kwargs):
        assert job_id==PILOT_JOB and kwargs['replay_visual']==rebuilt
        trace.append(('worker',job_id));return 0
    monkeypatch.setattr(cli,'run_job',worker)
    db=DB()
    if defect is None:
        assert replay.revalidate_job(PILOT_JOB,db)==0
        assert [x[1] for x in trace if x[0]=='event']==['coordinate_revalidation_started','coordinate_revalidation_complete']
    else:
        with pytest.raises((ValueError,RuntimeError)):replay.revalidate_job(PILOT_JOB,db)
        assert not any(x[0]=='worker' for x in trace)
        if defect=='late_correction':assert any(x[0]=='restore_review' for x in trace)
        if defect in ['archive_failure','correction','wrong_state']:assert not db.claimed
