import copy
import json
from datetime import datetime, timedelta
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import limitup as seeds
import limitup_outcomes as outcomes
import limitup_predictions as p

DAY = '2026-09-08'
STOCK = {'code':'000001','name':'模拟股票','boards':1,'market':'沪深主板','is_st':False,
         'first_seal':'09:30:00','last_seal':'09:35:00','breaks':0,'turnover':10,
         'seal_amount':100,'amount':1000,'float_cap':1e9,'price':10}

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(seeds,'now',lambda:datetime(2026,9,8,17,tzinfo=seeds.TZ))
    seed = {'date':DAY,'schema_version':1,'phase':'after_close','coverage':'source_complete','captured_at':'2026-09-08T16:00:00+08:00','stocks':[copy.deepcopy(STOCK)]}
    seeds.directory().mkdir(parents=True); seeds.atomic_save(seeds.directory()/f'{DAY}.json',seed)
    app=FastAPI();app.include_router(p.router)
    return seed,TestClient(app)


def sample_rows(days=65, n=20):
    rng=np.random.default_rng(32); rows=[]
    for i in range(days):
        date=(datetime(2026,1,1,tzinfo=seeds.TZ)+timedelta(days=i)).date().isoformat()
        for j in range(n):
            feature=(j%2)*10 + float(rng.normal(0,.02))
            positive=int(j%2 == 1)
            rows.append({'date':date,'code':f'{j:06d}','group':p.group(STOCK),'x':[feature,feature,feature,feature,feature,feature],
                         'y':{'up':positive,'touched':positive,'promoted':positive,'open_pct':feature+float(rng.normal()),'close_pct':feature+float(rng.normal())},
                         'available_at':(p.close_time(date)+timedelta(days=1)).isoformat(),
                         'feature_available_at':p.close_time(date).isoformat(),'target_date':(p.close_time(date)+timedelta(days=1)).date().isoformat()})
    return rows


def test_features_missing_and_market_separation():
    assert p.features(STOCK)[4] == .1
    assert p.features(STOCK|{'amount':0})[4] is None
    assert p.features(STOCK|{'first_seal':'bad'})[0] is None
    assert p.group(STOCK) != p.group(STOCK|{'market':'创业板'})
    assert p.group(STOCK) != p.group(STOCK|{'is_st':True})
    assert p.tier(STOCK|{'boards':None})=='未知'


def test_training_strict_time_and_label_availability():
    rows=sample_rows(3,2); cutoff=p.close_time('2026-01-03').replace(hour=9, minute=15)
    selected=p.training_before(rows,'2026-01-03',cutoff)
    assert {r['date'] for r in selected}=={'2026-01-01'}
    rows[0]['available_at']='2027-01-01T00:00:00+08:00'
    assert rows[0] not in p.training_before(rows,'2026-01-03',cutoff)


def test_neighbours_and_no_extrapolation():
    model=p.Neighbours(sample_rows(40),'up')
    pred=model.predict([10]*6)
    assert pred['value']>.9 and pred['n']==80 and pred['days']>=10
    assert model.predict([None]*4+[10]*2) is None
    assert model.predict([100000]*6) is None
    assert p.Neighbours(sample_rows(2),'up').predict([10]*6) is None


def test_fixed_temporal_validation_can_pass_signal():
    reports=p.validate(sample_rows())
    r=reports[p.group(STOCK)]['up']
    assert r['passed'],r
    assert r['n']==400 and r['days']==20
    assert r['score'] < r['baseline_score']
    assert all(pt['date'] >= '2026-02-15' for pt in r['points'])


def test_baseline_does_not_pass_and_single_class_rejected():
    points=[{'date':f'2026-02-{d:02d}','y':i%2,'value':.5,'baseline':.5} for d in range(1,21) for i in range(10)]
    r=p.assess(points,True,60)
    assert not r['passed'] and any('2%' in s for s in r['reasons'])
    assert not p.assess([x|{'y':1,'value':.99} for x in points],True,60)['passed']


def test_interval_gate_and_score():
    points=[{'date':f'2026-02-{d:02d}','y':i,'value':[.5,8.5],'baseline':[-10,20]} for d in range(1,21) for i in range(10)]
    r=p.assess(points,False,60)
    assert r['passed'] and r['coverage']==.8
    assert not p.assess([x|{'value':[0,9]} for x in points],False,60)['passed']
    assert p.interval_score(0,[1,3])==12


def test_insufficient_data_saved_without_probabilities(env):
    seed,client=env
    value=p.build(DAY)
    assert value['training_rows']==0 and all(e['value'] is None for e in value['rows'][0]['estimates'].values())
    reply=client.get('/api/market/limit-up-predictions/day',params={'date':DAY}).json()
    assert reply['snapshot']['id']==value['id'] and 'training_snapshot' not in reply['snapshot']
    assert reply['observations'][0]['feature_count']==6
    assert client.get('/api/market/limit-up-predictions/record',params={'date':DAY,'id':value['id']}).status_code==200
    p.build(DAY)
    assert len(list(p.root(DAY).glob('*.json')))==2


def test_future_or_late_sample_not_training(env,monkeypatch):
    seed,_=env
    monkeypatch.setattr(seeds,'now',lambda:datetime(2026,9,10,18,tzinfo=seeds.TZ))
    seed['captured_at']='2026-09-10T16:00:00+08:00'
    seeds.atomic_save(seeds.directory()/f'{DAY}.json',seed)
    rows,status=p.dataset(seeds.now())
    assert rows==[] and status['excluded']['样本采集超出研究时窗']==1


def test_dataset_joins_matching_mature_outcome(env,monkeypatch):
    seed,_=env
    monkeypatch.setattr(seeds,'now',lambda:datetime(2026,9,10,18,tzinfo=seeds.TZ))
    result={'date':DAY,'state':'complete','target_date':'2026-09-09','captured_at':'2026-09-09T17:00:00+08:00','seed_hash':outcomes.fingerprint(seed),
            'rows':[{'code':'000001','close_pct':-3,'open_pct':2,'touched':False,'promoted':None}]}
    seeds.atomic_save(outcomes.path_for(DAY),result)
    rows,status=p.dataset(seeds.now())
    assert len(rows)==1 and rows[0]['y']['up']==0 and rows[0]['y']['promoted'] is None
    result['seed_hash']='different';seeds.atomic_save(outcomes.path_for(DAY),result)
    assert not p.dataset(seeds.now())[0]


def test_stale_snapshot_not_used_for_actual_comparison(env):
    seed,client=env;p.build(DAY)
    seed['stocks'][0]['breaks']=3;seeds.atomic_save(seeds.directory()/f'{DAY}.json',seed)
    response=client.get('/api/market/limit-up-predictions/day',params={'date':DAY}).json()
    assert response['stale'] and response['snapshot'] is None and response['actual']=={}


def test_outside_window_no_estimates(env,monkeypatch):
    monkeypatch.setattr(seeds,'now',lambda:datetime(2026,9,10,18,tzinfo=seeds.TZ))
    value=p.build(DAY)
    assert not value['prospective']
    assert all(e['value'] is None for e in value['rows'][0]['estimates'].values())


def test_independent_release_and_prediction_freeze(env,monkeypatch):
    rows=sample_rows();key=p.group(STOCK)
    for r in rows:
        for field in ('date','target_date'):
            r[field]=(datetime.fromisoformat(r[field])+timedelta(days=185)).date().isoformat()
        for field in ('available_at','feature_available_at'):
            r[field]=(datetime.fromisoformat(r[field])+timedelta(days=185)).isoformat()
    monkeypatch.setattr(p,'dataset',lambda _: (rows,{'excluded':{}}))
    monkeypatch.setattr(p,'features',lambda _: [10]*6)
    reports={key:{t:{'passed':t=='up','reasons':[] if t=='up' else ['未通过'],'points':[]} for t in p.TARGETS}}
    monkeypatch.setattr(p,'validate',lambda *args:reports)
    first=p.build(DAY)
    e=first['rows'][0]['estimates']
    assert e['up']['value']>.9 and e['promoted']['value'] is None and e['close_pct']['value'] is None
    before=(p.root(DAY)/(first['id']+'.json')).read_bytes()
    rows[0]['y']['up']=1-rows[0]['y']['up'];p.build(DAY)
    assert (p.root(DAY)/(first['id']+'.json')).read_bytes()==before


def test_no_result_when_finishes_after_cutoff(env,monkeypatch):
    times=iter([datetime(2026,9,9,9,14,tzinfo=seeds.TZ),datetime(2026,9,9,9,16,tzinfo=seeds.TZ)])
    monkeypatch.setattr(seeds,'now',lambda:next(times))
    value=p.build(DAY)
    assert not value['prospective'] and '09:16' in value['generated_at']


def test_route_validation(env):
    _,client=env
    assert client.get('/api/market/limit-up-predictions/day?date=../../x').status_code==400
    assert client.get('/api/market/limit-up-predictions/record',params={'date':DAY,'id':'../../x'}).status_code==400
    assert client.get('/api/market/limit-up-predictions/record',params={'date':DAY,'id':'abc'}).status_code==404
