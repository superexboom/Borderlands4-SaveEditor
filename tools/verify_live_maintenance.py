"""Bounded 0.10.26 integration probe; restores the exact configured values."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live.bridge import Bridge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--combined', action='store_true')
    parser.add_argument('--seconds', type=float, default=3)
    parser.add_argument('--features', nargs='+', help='Optional exact runtime setting names to probe')
    args = parser.parse_args()
    b = Bridge(timeout=20)
    initial = b.runtime_action('maintenance_diagnostics')
    if initial.get('version') != '0.10.26' or not initial.get('pawn_available'):
        raise SystemExit('0.10.26 and a playable pawn are required')
    settings = initial['runtime_settings']
    cases = [(f'toggle_{key}', 'enabled', True, key) for key in (
        'skill_no_cd', 'repairkit_no_cd', 'gadget_no_cd', 'health_lock',
        'shield_lock', 'no_spread', 'no_recoil', 'instant_reload', 'no_overheat',
        'stamina_lock', 'guaranteed_crit')]
    cases += [(action, 'value', value, key) for action, value, key in (
        ('set_fire_rate', 2, 'fire_rate_scale'),
        ('set_movement_speed', 1.5, 'movement_speed_scale'),
        ('set_magazine_capacity_scale', 2, 'magazine_capacity_scale'),
        ('set_projectile_speed_scale', 2, 'projectile_speed_scale'),
        ('set_backpack_size', initial['state']['lost_loot']['backpack_max'] + 10, 'backpack_size'))]
    if args.features:
        unknown = set(args.features) - {row[3] for row in cases}
        if unknown:
            raise SystemExit(f'Unknown features: {sorted(unknown)}')
        cases = [row for row in cases if row[3] in args.features]
    out = ROOT / '.local/repair-runtime-20260919' / time.strftime('verified-026-%H%M%S.json')
    report = dict(version=initial['version'], revision=initial['revision'],
                  mode='combined' if args.combined else 'single', initial=initial, samples=[])
    groups = [cases] if args.combined else [[case] for case in cases]
    for group in groups:
        enabled = []
        try:
            for action, arg, value, key in group:
                enabled.append((action, arg, key))
                result = b.runtime_action(action, **{arg: value})
                if not result.get('ok'):
                    raise RuntimeError(f'{action}: {result.get("error")}')
            b.runtime_action('maintenance_diagnostics', clear=True)
            print('ACTIVE: ' + ', '.join(c[0] for c in group), flush=True)
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                time.sleep(min(5, max(0, deadline - time.monotonic())))
                d = b.runtime_action('maintenance_diagnostics', clear=True)
                s = d['stats']
                row = dict(actions=[c[0] for c in group], mean_ms=s['total_ms'] / max(1, s['runs']),
                           max_ms=s['max_ms'], runs=s['runs'], writes=s['writes'],
                           errors=d['maintain_errors'], pawn_available=d['pawn_available'])
                report['samples'].append(row)
                print(json.dumps(row), flush=True)
        finally:
            report.setdefault('restores', [])
            for action, arg, key in reversed(enabled):
                result = b.runtime_action(action, **{arg: settings[key]})
                report['restores'].append(dict(action=action, value=settings[key], ok=result.get('ok'),
                                               readback=result.get('readback'), error=result.get('error')))
            report['final'] = b.runtime_action('maintenance_diagnostics')
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    assert all(r['ok'] for r in report['restores']), 'A restore was not confirmed; inspect the report'
    final = report['final']['runtime_settings']
    assert all(final[key] == settings[key] for _, _, _, key in cases)
    print('RESTORED: ' + str(out))


if __name__ == '__main__':
    main()
