import importlib.util
import json
from pathlib import Path


def test_collector_writes_strict_json_for_unbounded_backtest_metrics(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('dashboard_collect', Path(__file__).parents[2] / 'dashboard/collect.py')
    collect = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collect)
    payload = {'symbols': {'BTC': {'sections': {'analysis': {'ok': True, 'data': {'price': 100}},
                                               'strategies': {'ok': True, 'data': {'profit_factor': float('inf'), 'total_return_pct': 2.5}}}}}}
    monkeypatch.setattr(collect, 'OUT', tmp_path / 'data.json')
    monkeypatch.setattr(collect, 'collect', lambda tier: payload)
    monkeypatch.setattr('sys.argv', ['collect.py', '--tier', 'daily'])
    assert collect.main() == 0
    def reject(value):
        raise ValueError('Non-standard JSON constant: ' + value)
    result = json.loads(collect.OUT.read_text(), parse_constant=reject)
    metrics = result['symbols']['BTC']['sections']['strategies']['data']
    assert metrics == {'profit_factor': None, 'total_return_pct': 2.5}
    assert payload['symbols']['BTC']['sections']['strategies']['data']['profit_factor'] == float('inf')
