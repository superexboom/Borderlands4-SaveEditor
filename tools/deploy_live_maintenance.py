"""Deploy the maintenance repair to the explicitly supplied BL4Live directory.

Copies and hashes the current files before touching them; refuses another version
or a concurrently modified entry point. Cold restart is explicit, never remote
arbitrary Python execution through the bridge.
"""
import argparse
import ast
import hashlib
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = '# BL4 maintenance repair bootstrap'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('game_mod',type=Path)
    parser.add_argument('--stage-running', action='store_true',
                        help='Stage files for next start; current process remains unchanged until explicit pyexec installation. Never rlm.')
    args=parser.parse_args()
    # Hot reload was followed by a GPU hang during validation. Its cause remains
    # unresolved; require a stopped game so this tool cannot encourage that path.
    if subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Borderlands4.exe', '/FO', 'CSV', '/NH'],
                      capture_output=True, text=True).stdout.lower().find('borderlands4.exe') >= 0 and not args.stage_running:
        raise SystemExit('Close Borderlands 4 before deployment; hot reload is not validated.')
    target=args.game_mod.resolve(); init=target/'__init__.py'
    raw=init.read_bytes();source=raw.decode('utf-8-sig')
    tree=ast.parse(source)
    versions=[ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
              and any(isinstance(t,ast.Name) and t.id=='__version__' for t in n.targets)]
    if versions not in (['0.10.25'], ['0.10.26']):
        raise SystemExit(f'Unsupported BL4Live version: {versions}')
    backup=ROOT/'.local/repair-runtime-20260919'/('deploy-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True)
    manifest={}
    for name in ('__init__.py','runtime_maintenance.py'):
        p=target/name
        if p.exists():
            shutil.copy2(p,backup/name)
            manifest[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    if MARKER in source:
        raise SystemExit('Existing repair bootstrap detected; inspect it before redeploying.')
    source = source.replace('__version__ = "0.10.25"', '__version__ = "0.10.26"', 1)
    source = source.replace('__version_info__ = (0, 10, 25)', '__version_info__ = (0, 10, 26)', 1)
    bootstrap = MARKER + '\nimport sys as _maintenance_sys\nfrom . import runtime_maintenance as _maintenance_module\n_maintenance_module.install(_maintenance_sys.modules[__name__])\n\n'
    # Install before on_enable registers the dispatcher, including cold starts.
    start_mod = source.index('mod = build_mod(')
    source = source[:start_mod] + bootstrap + source[start_mod:]
    # Delete obsolete FOV mutation dispatch; keep legacy restore functions solely
    # so an already-loaded old version can restore exact preexisting values.
    start=source.find('    if command_name in ("set_fov", "set_viewmodel_fov"):')
    if start>=0:
        end=source.index('    if command_name in ("set_magazine_capacity_scale", "set_projectile_speed_scale"):',start)
        source=source[:start]+source[end:]
    ast.parse(source)
    if init.read_bytes()!=raw:
        raise SystemExit('Entry point changed concurrently; backup saved, no deployment performed.')
    shutil.copy2(ROOT/'live/runtime_maintenance.py',target/'runtime_maintenance.py')
    init.write_text(source,encoding='utf8')
    manifest['deployed_sha256']=hashlib.sha256(init.read_bytes()).hexdigest()
    manifest['maintenance_sha256']=hashlib.sha256((target/'runtime_maintenance.py').read_bytes()).hexdigest()
    manifest['destination']=str(target)
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    print('Deployed to',target,'; rollback backup:',backup)
    print('Start a new game process to load this candidate. Do not use rlm bl4_live.')
    if args.stage_running:
        print('Running process is unchanged; verify maintenance_diagnostics after an explicit game-thread install.')

if __name__=='__main__':main()
