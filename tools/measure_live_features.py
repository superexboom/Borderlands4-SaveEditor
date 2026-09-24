"""Bounded integration benchmark; restores every tested setting in finally."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.bridge import Bridge

b = Bridge(timeout=30)
tag = sys.argv[1] if len(sys.argv) > 1 else 'before'
out = Path('.local/repair-runtime-20260919')
out.mkdir(parents=True, exist_ok=True)
original = b.runtime_action('state')['state']
cases = [(f'toggle_{k}', 'enabled', True, k) for k in (
    'skill_no_cd','repairkit_no_cd','gadget_no_cd','health_lock','shield_lock','no_spread','no_recoil',
    'instant_reload','no_overheat','stamina_lock','guaranteed_crit')]
cases += [(a,'value',v,k) for a,v,k in (
    ('set_fire_rate',2,'fire_rate_scale'),('set_movement_speed',1.5,'movement_speed_scale'),
    ('set_magazine_capacity_scale',2,'magazine_capacity_scale'),
    ('set_projectile_speed_scale',2,'projectile_speed_scale'),
    ('set_backpack_size',80,'backpack_size'))]
results = []
diagnostic = 'maintenance_diagnostics' if tag == 'final' else 'perf_probe'
for action, arg, value, key in cases:
    previous = original[key]
    try:
        started = time.perf_counter()
        response = b.runtime_action(action, **{arg:value})
        request_ms = (time.perf_counter()-started)*1000
        b.runtime_action(diagnostic, clear=True)
        time.sleep(1.2)
        sample = b.runtime_action(diagnostic,clear=True)
        row = dict(action=action, ok=response.get('ok'), error=response.get('error'),
                   request_ms=request_ms, functions=sample.get('functions',{}),
                   maintenance=sample.get('stats',{}), readback=response.get('readback'), writes=response.get('writes'))
        results.append(row)
        print(json.dumps(row), flush=True)
    finally:
        restored = b.runtime_action(action, **{arg:previous})
        if not restored.get('ok'):
            raise RuntimeError(f'Restore failed: {action}: {restored.get("error")}')
    (out/('features-'+tag+'.json')).write_text(json.dumps(results,indent=2),encoding='utf-8')
