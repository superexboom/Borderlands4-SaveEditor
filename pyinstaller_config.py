#!/usr/bin/env python3
"""
PyInstaller配置文件
用于生成Windows可执行文件
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def collect_data_files(folder: str, suffixes: tuple[str, ...]) -> list[tuple[str, str]]:
    files = []
    for file_path in sorted((BASE_DIR / folder).glob('*')):
        if file_path.suffix.lower() in suffixes:
            files.append((str(file_path), folder))
    return files


# 动态收集enhancement目录下的所有.csv和.json文件
enhancement_files = collect_data_files('enhancement', ('.csv', '.json'))
        
# 动态收集weapon_edit目录下的所有.csv和.json文件
weapon_files = collect_data_files('weapon_edit', ('.csv', '.json'))

# 动态收集grenade目录下的所有.csv和.json文件
grenade_files = collect_data_files('grenade', ('.csv', '.json'))

# 动态收集shield目录下的所有.csv和.json文件
shield_files = collect_data_files('shield', ('.csv', '.json'))

# 动态收集repkit目录下的所有.csv和.json文件
repkit_files = collect_data_files('repkit', ('.csv', '.json'))

# 动态收集heavy目录下的所有.csv和.json文件
heavy_files = collect_data_files('heavy', ('.csv', '.json'))

# 动态收集loadout目录下的所有.csv和.json文件
loadout_files = collect_data_files('loadout', ('.csv', '.json'))

# 动态收集item目录下的索引文件
item_files = collect_data_files('item', ('.json',))

# 动态收集i18n目录下的所有本地化文件
i18n_files = collect_data_files('i18n', ('.json',))

# 动态收集core/data目录下的解锁数据文件
core_data_files = collect_data_files('core/data', ('.txt', '.json', '.csv'))

# 收集assets目录下的资源文件
assets_files = [
    (str(BASE_DIR / 'assets/stylesheet.qss'), 'assets'),
    (str(BASE_DIR / 'assets/BL4.ico'), 'assets'),
    (str(BASE_DIR / 'assets/bg.jpg'), 'assets'),
] + collect_data_files('assets/item_stats_icon', ('.png',)) + collect_data_files('assets/item_card_type', ('.png',))


# PyInstaller spec文件内容
SPEC_CONTENT = f'''
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    [r'{str(BASE_DIR / "main_window.py")}'],
    pathex=[r'{str(BASE_DIR)}'],
    binaries=[],
    datas=[
        (r'{str(BASE_DIR / "class_mods" / "*.json")}', 'class_mods'),
        (r'{str(BASE_DIR / "class_mods" / "*.csv")}', 'class_mods'),
        (r'{str(BASE_DIR / "class_mods" / "Amon" / "*.png")}', 'class_mods/Amon'),
        (r'{str(BASE_DIR / "class_mods" / "C4sh" / "*.png")}', 'class_mods/C4sh'),
        (r'{str(BASE_DIR / "class_mods" / "Harlowe" / "*.png")}', 'class_mods/Harlowe'),
        (r'{str(BASE_DIR / "class_mods" / "Rafa" / "*.png")}', 'class_mods/Rafa'),
        (r'{str(BASE_DIR / "class_mods" / "Vex" / "*.png")}', 'class_mods/Vex'),
    ] + {enhancement_files} + {weapon_files} + {grenade_files} + {shield_files} + {repkit_files} + {heavy_files} + {loadout_files} + {item_files} + {i18n_files} + {core_data_files} + {assets_files},
    hiddenimports=[
        'pandas',
        'yaml',
        'Crypto.Cipher',
        'Crypto.Util.Padding',
        'core',
        'core.resource_loader',
        'core.bl4_functions',
        'core.decoder_logic',
        'core.b_encoder',
        'core.item_display_resolver',
        'core.weapon_display_stats',
        'core.unlock_logic',
        'core.unlock_data',
        'core.save_game_controller',
        'core.save_selector_widget',
        'core.theme_manager',
        'core.lookup',
        'tabs',
        'tabs.qt_character_tab',
        'tabs.qt_items_tab',
        'tabs.qt_converter_tab',
        'tabs.qt_yaml_editor_tab',
        'tabs.qt_catalog_picker',
        'tabs.qt_class_mod_editor_tab',
        'tabs.qt_enhancement_editor_tab',
        'tabs.qt_weapon_editor_tab',
        'tabs.qt_weapon_generator_tab',
        'tabs.qt_grenade_editor_tab',
        'tabs.qt_shield_editor_tab',
        'tabs.qt_repkit_editor_tab',
        'tabs.qt_heavy_weapon_editor_tab',
        'tabs.qt_loadout_manager_tab',
        'bl4_decoder_py',
    ],
    hookspath=[],
    hooksconfig=[],
    runtime_hooks=[],
    excludes=['PIL'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='BL4SaveEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=r"{str(BASE_DIR / 'assets' / 'BL4.ico')}",
)
'''

def create_spec_file():
    """创建PyInstaller spec文件"""
    spec_path = BASE_DIR / 'BL4SaveEditor.spec'
    # 使用f-string来格式化SPEC_CONTENT
    with open(spec_path, 'w', encoding='utf-8') as f:
        f.write(SPEC_CONTENT)
    print(f"Created spec file: {spec_path}")
    return spec_path

def build_executable():
    """构建可执行文件"""
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller not installed. Installing...")
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'pyinstaller'])
    
    spec_path = create_spec_file()
    
    print("Building executable...")
    import subprocess
    result = subprocess.run([
        sys.executable, '-m', 'PyInstaller',
        '--clean',
        '--noconfirm',
        str(spec_path)
    ], capture_output=True, text=True, cwd=str(BASE_DIR))
    
    if result.returncode == 0:
        print("Build successful!")
        print("Executable location: dist/BL4SaveEditor.exe")
    else:
        print("Build failed!")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
    
    return result.returncode == 0

if __name__ == "__main__":
    print("=== PyInstaller Configuration ===")
    print("This script will help you build a Windows executable for BL4 Save Editor")
    print("Make sure all dependencies are installed:")
    print("  pip install pyinstaller pyyaml pycryptodome pandas PyQt6")
    print()
    
    response = input("Do you want to build the executable now? (y/n): ")
    if response.lower() == 'y':
        success = build_executable()
        if success:
            print("\nBuild completed successfully!")
            print("You can find the executable in the 'dist' folder.")
        else:
            print("\nBuild failed. Please check the error messages above.")
    else:
        print("Build cancelled. You can run this script later to build the executable.")
