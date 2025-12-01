#!/usr/bin/env python3
"""
PyInstaller配置文件
用于生成Windows可执行文件
"""

import sys
import glob
from pathlib import Path

# 动态收集enhancement目录下的所有.txt和.json文件
enhancement_files = []
for file_path in glob.glob('enhancement/*'):
    if file_path.endswith('.txt') or file_path.endswith('.json'):
        enhancement_files.append((file_path, 'enhancement'))
        
# 动态收集weapon_edit目录下的所有.csv和.json文件
weapon_files = []
for file_path in glob.glob('weapon_edit/*'):
    if file_path.endswith('.csv') or file_path.endswith('.json'):
        weapon_files.append((file_path, 'weapon_edit'))

# 动态收集grenade目录下的所有.csv和.json文件
grenade_files = []
for file_path in glob.glob('grenade/*'):
    if file_path.endswith('.csv') or file_path.endswith('.json'):
        grenade_files.append((file_path, 'grenade'))

# 动态收集shield目录下的所有.csv和.json文件
shield_files = []
for file_path in glob.glob('shield/*'):
    if file_path.endswith('.csv') or file_path.endswith('.json'):
        shield_files.append((file_path, 'shield'))

# 动态收集repkit目录下的所有.csv和.json文件
repkit_files = []
for file_path in glob.glob('repkit/*'):
    if file_path.endswith('.csv') or file_path.endswith('.json'):
        repkit_files.append((file_path, 'repkit'))

# 动态收集heavy目录下的所有.csv和.json文件
heavy_files = []
for file_path in glob.glob('heavy/*'):
    if file_path.endswith('.csv') or file_path.endswith('.json'):
        heavy_files.append((file_path, 'heavy'))

# 动态收集根目录下的item_localization_zh-CN.json文件
root_files = [
    ('item_localization_zh-CN.json', '.'),
    ('ui_localization.json', '.'),
    ('ui_localization_EN.json', '.'),
    ('stylesheet.qss', '.'),
    ('BL4.ico', '.'),
]


# PyInstaller spec文件内容
SPEC_CONTENT = f'''
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main_window.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('class_mods/*.json', 'class_mods'),
        ('class_mods/Amon/*.png', 'class_mods/Amon'),
        ('class_mods/Harlowe/*.png', 'class_mods/Harlowe'),
        ('class_mods/Rafa/*.png', 'class_mods/Rafa'),
        ('class_mods/Vex/*.png', 'class_mods/Vex'),
    ] + {enhancement_files} + {weapon_files} + {grenade_files} + {shield_files} + {repkit_files} + {heavy_files} + {root_files},
    hiddenimports=[
        'PIL',
        'pandas',
        'PIL.Image',
        'PIL.ImageTk',
        'yaml',
        'Crypto.Cipher',
        'Crypto.Util.Padding',
        'resource_loader',
        'bl4_functions',
        'decoder_logic',
        'b_encoder',
        'unlock_logic',
        'unlock_data',
        'save_game_controller',
        'save_selector_widget',
        'qt_character_tab',
        'qt_items_tab',
        'qt_converter_tab',
        'qt_yaml_editor_tab',
        'qt_class_mod_editor_tab',
        'qt_enhancement_editor_tab',
        'qt_weapon_editor_tab',
        'qt_weapon_generator_tab',
        'qt_grenade_editor_tab',
        'qt_shield_editor_tab',
        'qt_repkit_editor_tab',
        'qt_heavy_weapon_editor_tab',
        'bl4_decoder_py',
    ],
    hookspath=[],
    hooksconfig=[],
    runtime_hooks=[],
    excludes=[],
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="BL4.ico",
)
'''

def create_spec_file():
    """创建PyInstaller spec文件"""
    spec_path = Path('BL4SaveEditor.spec')
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
    ], capture_output=True, text=True)
    
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
    print("  pip install pyinstaller pillow pyyaml pycryptodome pandas PyQt6")
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
