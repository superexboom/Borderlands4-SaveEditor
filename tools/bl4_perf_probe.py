"""Load with `pyexec bl4_perf_probe.py` in the game console. No gameplay writes."""
import collections
import time
import bl4_live as m

if not hasattr(m, '_perf_originals'):
    m._perf_originals = {}
    m._perf_samples = {}
    names = ('_runtime_maintain', '_runtime_apply_fov', '_runtime_apply_weapon_features',
             '_runtime_apply_player_features', '_runtime_apply_jump_scale',
             '_runtime_apply_infinite_jump', '_runtime_apply_backpack_size',
             '_runtime_refresh_xp_context', '_runtime_owned', '_runtime_weapon_behavior_pairs',
             '_runtime_selected_action_skill', '_runtime_write', '_runtime_static')
    def wrap(name, fn):
        def timed(*args, **kwargs):
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                rows = m._perf_samples.setdefault(name, collections.deque(maxlen=2048))
                rows.append((time.perf_counter() - start) * 1000)
        return timed
    for name in names:
        fn = getattr(m, name, None)
        if callable(fn):
            m._perf_originals[name] = fn
            setattr(m, name, wrap(name, fn))
    m._perf_action_original = m._runtime_action
    def action(name, params=None):
        if name == 'perf_probe':
            result = {}
            for key, samples in m._perf_samples.items():
                rows = sorted(samples)
                if rows:
                    result[key] = dict(n=len(rows), mean_ms=sum(rows)/len(rows),
                                       p95_ms=rows[min(len(rows)-1,int(len(rows)*.95))], max_ms=max(rows))
            if (params or {}).get('clear'):
                m._perf_samples.clear()
            return dict(ok=True, functions=result, version=m.__version__)
        return m._perf_action_original(name, params)
    m._runtime_action = action
    m._log('Temporary performance probe installed (perf_probe).')
