"""Part tables of the four equipment editors (grenade, shield, repkit, heavy weapon).

Each loader returns ``(main perks, manufacturer/rarity parts, zh-CN localization)`` and is
cached per language.
"""

from functools import lru_cache

import pandas as pd

from core import resource_loader


@lru_cache(maxsize=None)
def load_grenade_data(lang='zh-CN'):
    try:
        df_main = resource_loader.load_localized_csv_resource('data/grenade/grenade_main_perk.csv', lang)
        df_mfg = resource_loader.load_localized_csv_resource('data/grenade/manufacturer_rarity_perk.csv', lang)
        localization = {}
        if lang == 'zh-CN':
            localization = resource_loader.load_json_resource('data/grenade/Grenade_localization_zh-CN.json') or {}
        return df_main, df_mfg, localization
    except Exception as e:
        print(f"Error loading grenade data ({lang}): {e}")
        return None, None, None


@lru_cache(maxsize=None)
def load_shield_data(lang='zh-CN'):
    try:
        df_main = resource_loader.load_localized_csv_resource('data/shield/shield_main_perk.csv', lang)
        df_mfg = resource_loader.load_localized_csv_resource('data/shield/manufacturer_perk.csv', lang)
        localization = {}
        if lang == 'zh-CN':
            localization = resource_loader.load_json_resource('data/shield/Shield_localization_zh-CN.json') or {}
        return df_main, df_mfg, localization
    except Exception as e:
        print(f"Error loading shield data: {e}")
        return None, None, None


@lru_cache(maxsize=None)
def load_repkit_data(lang='zh-CN'):
    try:
        df_main = resource_loader.load_localized_csv_resource('data/repkit/repkit_main_perk.csv', lang)
        df_mfg = resource_loader.load_localized_csv_resource('data/repkit/repkit_manufacturer_perk.csv', lang)
        localization = {}
        if lang == 'zh-CN':
            localization = resource_loader.load_json_resource('data/repkit/Repkit_localization_zh-CN.json') or {}
        return df_main, df_mfg, localization
    except Exception as e:
        print(f"Error loading repkit data: {e}")
        return None, None, None


@lru_cache(maxsize=None)
def load_heavy_weapon_data(lang='zh-CN'):
    try:
        df_main = resource_loader.load_localized_csv_resource('data/heavy/heavy_main_perk.csv', lang)
        df_parts = resource_loader.load_localized_csv_resource('data/heavy/heavy_manufacturer_perk.csv', lang)
        # Rarity rows live in their own file, as they already do for the other three
        # equipment families (grenade/manufacturer_rarity_perk.csv, shield/manufacturer_perk.csv,
        # repkit/repkit_manufacturer_perk.csv). Keeping them out of the part file lets the
        # part file carry ids and names only, with descriptions coming from the index. The
        # rarity file keeps its Description column because that is where the legendary skin
        # names live, and those have no other source.
        df_rarity = resource_loader.load_localized_csv_resource('data/heavy/heavy_rarity.csv', lang)
        df_mfg = pd.concat([df_parts, df_rarity], ignore_index=True)
        df_mfg['Manufacturer ID'] = pd.to_numeric(df_mfg['Manufacturer ID'], errors='coerce')
        df_mfg.dropna(subset=['Manufacturer ID'], inplace=True)
        df_mfg['Manufacturer ID'] = df_mfg['Manufacturer ID'].astype(int)
        localization = {}
        if lang == 'zh-CN':
            localization = resource_loader.load_json_resource('data/heavy/Heavy_localization_zh-CN.json') or {}
        return df_main, df_mfg, localization
    except Exception as e:
        print(f"Error loading heavy weapon data: {e}")
        return None, None, None
