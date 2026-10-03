"""Forward observations are immutable and cannot borrow historical outcomes."""
import importlib
import copy
import pytest
from test_entry_strategy import trend_bars, quarters
from entrydesk.signals import evaluate


def journal(path):
    assert importlib.util.find_spec('entrydesk.journal'), 'Forward observation journal is missing'
    return importlib.import_module('entrydesk.journal').Journal(path)


def setup(side='LONG'):
    bars=trend_bars(side)
    now=bars[-1]['end']+1
    bundle=dict(symbol='BTC-USD',asset_class='crypto',source='yahoo',bars_1h=bars,bars_15m=quarters(bars),errors=[],quote=None)
    return bundle,evaluate(bundle,now),now


def later(bundle, count=2):
    out=copy.deepcopy(bundle);last=out['bars_1h'][-1];price=last['close'];start=last['end']
    for i in range(count):
        out['bars_1h'].append(dict(start=start+i*3600,end=start+(i+1)*3600,open=price,
            high=price+4 if i else price+.1,low=price-.1,close=price,volume=100))
    return out


def test_journal_deduplicates_and_preserves_first_observation_on_revision(tmp_path):
    path=tmp_path/'observations.sqlite3';j=journal(path);bundle,candidate,now=setup()
    first=j.observe(bundle,candidate,now)
    j.observe(bundle,dict(candidate,score=999),now+10)
    summary=j.summary();assert summary['observations']==1
    assert summary['recent'][0]['observed_at']==now
    assert summary['recent'][0]['score']!=999
    assert summary['recent'][0]['input_hash']==first['input_hash']
    j.close();j=journal(path)
    assert j.summary()['observations']==1
    j.close()


def test_shadow_enters_only_after_recording_and_does_not_relabel_as_paper(tmp_path):
    j=journal(tmp_path/'observations.sqlite3');bundle,candidate,now=setup()
    j.observe(bundle,candidate,now)
    extended=later(bundle)
    j.resolve(extended,extended['bars_1h'][-1]['end']+1)
    summary=j.summary();row=summary['recent'][0]
    assert row['outcome']['origin']=='forward_shadow'
    assert row['outcome']['entry_time']>now
    assert row['outcome']['entry_time']==bundle['bars_1h'][-1]['end']+3600
    assert row['outcome']['closed'] is True
    assert summary['forward_paper_closes']==0
    j.resolve(extended,extended['bars_1h'][-1]['end']+2)
    assert j.summary()['closed_shadow']==1
    j.close()


def test_future_bars_never_resolve_outcomes_and_unfinished_trade_stays_open(tmp_path):
    j=journal(tmp_path/'observations.sqlite3');bundle,candidate,now=setup();j.observe(bundle,candidate,now)
    extended=later(bundle,1)
    with pytest.raises(ValueError):j.resolve(extended,now)
    j.resolve(extended,extended['bars_1h'][-1]['end'])
    assert j.summary()['closed_shadow']==0
    j.close()


def test_short_stale_and_commodity_signals_are_recorded_without_shadow_fills(tmp_path):
    for changes in ({'stale':True},{'asset_class':'commodities'},{}):
        j=journal(tmp_path/(str(len(changes))+str(changes.get('asset_class'))+'.sqlite3'))
        bundle,candidate,now=setup('SHORT' if not changes else 'LONG');bundle.update(changes)
        j.observe(bundle,evaluate(bundle,now),now)
        extended=later(bundle);j.resolve(extended,extended['bars_1h'][-1]['end']+1)
        assert j.summary()['closed_shadow']==0
        assert j.summary()['recent'][0]['shadow_eligible'] is False
        j.close()


def test_missing_first_forward_bar_cannot_create_late_fill(tmp_path):
    j=journal(tmp_path/'observations.sqlite3');bundle,candidate,now=setup();j.observe(bundle,candidate,now)
    extended=later(bundle,5);del extended['bars_1h'][-4:-1]
    j.resolve(extended,extended['bars_1h'][-1]['end']+1)
    outcome=j.summary()['recent'][0]['outcome']
    assert outcome['status'] in ('expired','unavailable') and not outcome.get('closed')
    j.close()


def test_open_shadow_entry_bar_is_immutable_when_provider_revises_it(tmp_path):
    j=journal(tmp_path/'observations.sqlite3');bundle,candidate,now=setup();j.observe(bundle,candidate,now)
    extended=later(bundle,2);extended['bars_1h'][-1]['high']=extended['bars_1h'][-1]['close']+.1
    j.resolve(extended,extended['bars_1h'][-1]['end']+1)
    assert j.summary()['closed_shadow']==0
    revised=copy.deepcopy(extended)
    revised['bars_1h'][-1]['open']+=.05;revised['bars_1h'][-1]['high']+=10
    last=revised['bars_1h'][-1]
    revised['bars_1h'].append(dict(last,start=last['end'],end=last['end']+3600,open=last['close'],high=last['close']+4))
    j.resolve(revised,revised['bars_1h'][-1]['end']+1)
    outcome=j.summary()['recent'][0]['outcome']
    assert outcome['entry']==extended['bars_1h'][-1]['open']
    assert outcome['exit_time']==revised['bars_1h'][-1]['end']
    j.close()


def test_collect_wires_confirmed_replay_and_journal_but_demo_is_isolated(tmp_path,monkeypatch):
    import json, subprocess
    import entrydesk.__main__ as cli
    from entrydesk.validation import backtest
    bundle,candidate,now=setup()
    calls=[]
    def run(args,**kwargs):
        if kwargs.get('input'):
            inputs=json.loads(kwargs['input']);calls.append(inputs)
            result=backtest(*inputs)
        else: result=bundle
        return subprocess.CompletedProcess(args,0,json.dumps(result),'')
    monkeypatch.setattr(cli.subprocess,'run',run)
    monkeypatch.setattr(cli.time,'time',lambda:now)
    history=tmp_path/'history';out=tmp_path/'entries.json'
    cli.main(['collect','--symbols','BTC-USD','--history-dir',str(history),'--output',str(out)])
    payload=json.loads(out.read_text())
    assert len(calls[0])==3 and calls[0][2]==bundle['bars_15m']
    assert payload['journal']['observations']==1
    before=(history/'observations.sqlite3').stat().st_mtime_ns
    cli.main(['demo','--history-dir',str(history),'--output',str(tmp_path/'demo.json')])
    assert (history/'observations.sqlite3').stat().st_mtime_ns==before
