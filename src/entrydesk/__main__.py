"""Explicit live collection, saved-history validation, and isolated synthetic demo."""
import argparse
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

from .signals import evaluate
from .validation import backtest

DEFAULTS = {'stocks': 'SPY,NVDA,AMD,AVGO,ASML,TSM,MU,INTC,QCOM,AMAT,LRCX,KLAC,ARM'.split(','),
            'crypto': ['BTC-USD', 'ETH-USD'], 'commodities': ['GC=F', 'SI=F', 'CL=F']}


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, allow_nan=False, indent=2) + '\n')
    os.replace(temporary, path)


def demo_bundle():
    rng, bars, price = random.Random(17), [], 100.
    for i in range(300):
        opening = price
        price = max(1., price + rng.uniform(-1., 1.))
        bars.append(dict(start=i*3600, end=(i+1)*3600, open=opening,
                         high=max(opening, price)+.5, low=min(opening, price)-.5,
                         close=price, volume=100 + rng.randrange(100)))
    return dict(symbol='SYNTHETIC', asset_class='stocks', source='synthetic_demo',
                contract_kind='synthetic', currency='USD', bars_1h=bars, bars_15m=[],
                quote=None, market_open=False, errors=[])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', choices=['collect', 'validate', 'demo'], default='collect')
    parser.add_argument('--mode', choices=['collect', 'validate', 'demo'])
    parser.add_argument('--symbols', help='comma-separated default ticker subset')
    parser.add_argument('--max-seconds', type=float, default=120)
    parser.add_argument('--output', type=Path, default=Path('docs/entries.json'))
    parser.add_argument('--history-dir', type=Path, default=Path('.screener/entrydesk'))
    args = parser.parse_args(argv)
    command = args.mode or args.command
    if args.max_seconds <= 0:
        parser.error('--max-seconds must be positive')
    selected = set(args.symbols.split(',')) if args.symbols else None
    known = {s for symbols in DEFAULTS.values() for s in symbols}
    if selected and selected - known:
        parser.error('unknown symbols: ' + ','.join(sorted(selected-known)))
    now, deadline = time.time(), time.monotonic() + args.max_seconds
    payload = dict(version=1, generated_at=now, candidates=[], validation={}, status='ok', errors=[])
    if command == 'demo':
        bundle = demo_bundle()
        report = backtest(bundle['bars_1h'], bundle['asset_class'])
        payload.update(status='synthetic_demo')
        payload['validation'][bundle['symbol']] = report
        payload['candidates'].append(evaluate(bundle, bundle['bars_1h'][-1]['end'], report))
    else:
        from .data import validate_bars
        for asset_class, symbols in DEFAULTS.items():
            for symbol in symbols:
                if selected and symbol not in selected:
                    continue
                if time.monotonic() >= deadline:
                    payload['errors'].append('collection deadline reached before ' + symbol)
                    continue
                path = args.history_dir / (symbol.replace('=', '_').replace('/', '_') + '.json')
                try:
                    if command == 'validate':
                        bundle = json.loads(path.read_text())
                    else:
                        # A process boundary enforces a total deadline even if a provider stalls.
                        script = ('import json,time; from entrydesk.data import collect_symbol; '
                                  'print(json.dumps(collect_symbol(' + repr(symbol) + ',' + repr(asset_class) + ',time.time()),allow_nan=False))')
                        completed = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
                                                   timeout=max(.01, deadline-time.monotonic()), check=True)
                        bundle = json.loads(completed.stdout)
                        if not bundle.get('bars_1h'):
                            raise ValueError('; '.join(bundle.get('errors', [])) or 'hourly data unavailable')
                        validate_bars(bundle['bars_1h'], time.time())
                        atomic_json(path, bundle)
                        payload['errors'].extend(symbol + ': ' + warning for warning in bundle.get('errors', []))
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    payload['errors'].append(symbol + ': ' + str(exc))
                    try:
                        bundle = json.loads(path.read_text())
                        bundle['stale'] = True
                        bundle.setdefault('errors', []).append('cached after provider failure')
                    except (OSError, ValueError):
                        bundle = dict(symbol=symbol, asset_class=asset_class, errors=['collection failed'], stale=True)
                try:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError('validation deadline reached')
                    script = ('import json,sys; from entrydesk.validation import backtest; '
                              'b=json.load(sys.stdin); print(json.dumps(backtest(b[0],b[1]),allow_nan=False))')
                    completed = subprocess.run([sys.executable, '-c', script],
                        input=json.dumps([bundle.get('bars_1h', []), asset_class], allow_nan=False),
                        capture_output=True, text=True, timeout=remaining, check=True)
                    report = json.loads(completed.stdout)
                except (ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
                    payload['errors'].append(symbol + ': validation ' + str(exc))
                    report = dict(ready=False, reasons=[str(exc)])
                payload['validation'][symbol] = report
                payload['candidates'].append(evaluate(bundle, time.time(), report))
        if payload['errors']:
            payload['status'] = 'partial'
    atomic_json(args.output, payload)
    return 1 if payload['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
