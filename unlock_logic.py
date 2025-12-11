import uuid
import copy
from unlock_data import (
    COLLECTIBLES, MISSIONSETS, UNLOCKABLES, LOCATIONS,
    CHARACTER_CLASSES, MAX_LEVEL, SAFEHOUSE_SILO_LOCATIONS
)

# --- Helper Functions ---

def get_or_create_dict(d, key):
    if key not in d or not isinstance(d[key], dict):
        d[key] = {}
    return d[key]

def get_or_create_list(d, key):
    if key not in d or not isinstance(d[key], list):
        d[key] = []
    return d[key]

# --- Exploration Logic ---

def clear_map_fog(data):
    levelnames = [
        'Intro_P', 'World_P', 'Vault_Grasslands_P', 'Fortress_Grasslands_P',
        'Vault_ShatteredLands_P', 'Fortress_Shatteredlands_P', 'Vault_Mountains_P',
        'Fortress_Mountains_P', 'ElpisElevator_P', 'Elpis_P', 'UpperCity_P'
    ]
    common_fields = {
        'foddimensionx': 128,
        'foddimensiony': 128,
        'compressiontype': 'Zlib',
        'foddata': 'eJztwTEBAAAAwqD+qWcMH6AAAAAAAAAAAAAAAAAAAACAtwGw2cOy',
    }

    gbx = get_or_create_dict(data, 'gbx_discovery_pc')
    foddatas = get_or_create_list(gbx, 'foddatas')

    for levelname in levelnames:
        new_entry = common_fields.copy()
        new_entry['levelname'] = levelname
        
        found = False
        for i, entry in enumerate(foddatas):
            if entry.get('levelname') == levelname:
                foddatas[i] = new_entry
                found = True
                break
        if not found:
            foddatas.append(new_entry)

    visit_all_worlds(data)

def visit_all_worlds(data):
    worldlist = [
        'Intro_P', 'World_P', 'Fortress_Grasslands_P', 'Vault_Grasslands_P',
        'Fortress_Shatteredlands_P', 'Vault_ShatteredLands_P', 'Fortress_Mountains_P',
        'Vault_Mountains_P', 'ElpisElevator_P', 'Elpis_P', 'UpperCity_P'
    ]
    regionlist = [
        'KairosGeneric', 'grasslands_Prison', 'grasslands_RegionA', 'grasslands_RegionB',
        'grasslands_RegionC', 'grasslands_RegionD', 'grasslands_RegionE', 'Grasslands_Fortress',
        'Grasslands_Vault', 'shatteredlands_RegionA', 'shatteredlands_RegionB',
        'shatteredlands_RegionC', 'shatteredlands_RegionD', 'shatteredlands_RegionE',
        'shatteredlands_Fortress', 'shatteredlands_Vault', 'mountains_RegionA',
        'mountains_RegionB', 'mountains_RegionC', 'mountains_RegionD', 'mountains_RegionE',
        'Mountains_Fortress', 'Mountains_Vault', 'elpis_elevator', 'elpis', 'city_RegionA',
        'city_RegionB', 'city_RegionC', 'city_Upper'
    ]
    regionlist.sort(key=lambda x: x.lower())

    gbx = get_or_create_dict(data, 'gbx_discovery_pc')
    metrics = get_or_create_dict(gbx, 'metrics')
    
    hasseenworldlist = get_or_create_list(metrics, 'hasseenworldlist')
    for w in worldlist:
        if w not in hasseenworldlist:
            hasseenworldlist.append(w)
            
    hasseenregionlist = get_or_create_list(metrics, 'hasseenregionlist')
    for r in regionlist:
        if r not in hasseenregionlist:
            hasseenregionlist.append(r)
    
    metrics['hasseenregionlist'] = sorted(hasseenregionlist, key=lambda x: x.lower())

def add_discovered_locations(data, location_substrings):
    pg = get_or_create_dict(data, 'gbx_discovery_pg')
    existing_blob = pg.get('dlblob', '')
    # Python split might behave differently with regex, approximating JS logic
    # existing = existingBlob.split(/:\d:/).filter(Boolean);
    # The separator seems to be :1:, :2:, etc. LOCATIONS are strings.
    # JS logic: split by /:\d:/
    import re
    existing = [x for x in re.split(r':\d:', existing_blob) if x]
    
    merged = set(existing)
    for line in LOCATIONS:
        for substr in location_substrings:
            if substr in line:
                merged.add(line)
                break # optimization: found one match for this line
    
    pg['dlblob'] = ':2:'.join(merged) + ':2:'

def discover_all_locations(data):
    add_discovered_locations(data, [''])
    complete_discovery_achievements(data)

def discover_safehouse_locations(data):
    prefix = 'DLMD_World_P_PoAActor_UAID_'
    location_substrings = [prefix + id_ for id_ in SAFEHOUSE_SILO_LOCATIONS]
    add_discovered_locations(data, location_substrings)

# --- Counters & Collectibles Logic ---

def update_stats_counters(data, counters, category='challenge'):
    stats = get_or_create_dict(data, 'stats')
    cat_dict = get_or_create_dict(stats, category)
    
    for key, value in counters.items():
        # Handle nested dictionaries if any (e.g. in complete_phosphene_challenges)
        if isinstance(value, dict):
            sub_dict = get_or_create_dict(cat_dict, key)
            for sub_key, sub_value in value.items():
                prev = sub_dict.get(sub_key)
                if prev is None or (isinstance(sub_value, (int, float)) and sub_value > prev):
                    sub_dict[sub_key] = sub_value
        else:
            prev = cat_dict.get(key)
            if prev is None or (isinstance(value, (int, float)) and value > prev):
                cat_dict[key] = value

def complete_all_collectibles(data):
    stats = get_or_create_dict(data, 'stats')
    openworld = get_or_create_dict(stats, 'openworld')
    collectibles = get_or_create_dict(openworld, 'collectibles')
    
    for category, values in COLLECTIBLES.items():
        if isinstance(values, dict):
            cat_dict = get_or_create_dict(collectibles, category)
            for k, v in values.items():
                if isinstance(v, dict):
                    k_dict = get_or_create_dict(cat_dict, k)
                    for kk, vv in v.items():
                        k_dict[kk] = vv
                else:
                    cat_dict[k] = v
        else:
            collectibles[category] = values
            
    # Eridian/Nyriad ECHO logs
    state = get_or_create_dict(data, 'state')
    state['seen_eridium_logs'] = 262143
    
    update_sdu_points(data)

def unlock_vault_powers(data):
    stats = get_or_create_dict(data, 'stats')
    openworld = get_or_create_dict(stats, 'openworld')
    collectibles = get_or_create_dict(openworld, 'collectibles')
    
    collectibles['vaultpower_grasslands'] = 1
    collectibles['vaultpower_shatteredlands'] = 1
    collectibles['vaultpower_mountains'] = 1

def unlock_postgame(data):
    globals_ = get_or_create_dict(data, 'globals')
    globals_['highest_unlocked_vault_hunter_level'] = 5
    globals_['vault_hunter_level'] = 1
    
    complete_uvh_challenges(data)
    merge_missionsets_with_prefix(data, 'missionset_main_postgame')

def set_story_values(data):
    globals_ = get_or_create_dict(data, 'globals')
    globals_['lockdownlifted'] = True
    
    stats = get_or_create_dict(data, 'stats')
    challenge = get_or_create_dict(stats, 'challenge')
    challenge['mission_main_all'] = 18
    
    unlockables_dict = get_or_create_dict(data, 'unlockables')
    char_progress = get_or_create_dict(unlockables_dict, 'character_progress')
    entries = get_or_create_list(char_progress, 'entries')
    
    if 'character_progress.seen_credits' not in entries:
        entries.append('character_progress.seen_credits')

# --- Missions Logic ---

def get_missionsets_with_prefix(prefix):
    result = {}
    for key, value in MISSIONSETS.items():
        if key.startswith(prefix):
            result[key] = value
    return result

def merge_missionsets_with_prefix(data, prefix):
    filtered_missionsets = get_missionsets_with_prefix(prefix)
    
    missions = get_or_create_dict(data, 'missions')
    local_sets = get_or_create_dict(missions, 'local_sets')
    
    for key, value in filtered_missionsets.items():
        local_sets[key] = copy.deepcopy(value)

def complete_all_missions(data):
    merge_missionsets_with_prefix(data, 'missionset_')
    stage_epilogue_mission(data)
    set_story_values(data)
    open_all_vault_doors(data)
    discover_safehouse_locations(data)
    update_sdu_points(data)

def complete_all_story_missions(data):
    merge_missionsets_with_prefix(data, 'missionset_main_')
    stage_epilogue_mission(data)
    set_story_values(data)

def complete_all_safehouse_missions(data):
    merge_missionsets_with_prefix(data, 'missionset_zoneactivity_safehouse')
    merge_missionsets_with_prefix(data, 'missionset_zoneactivity_silo')
    discover_safehouse_locations(data)
    update_sdu_points(data)

def stage_epilogue_mission(data):
    missions = get_or_create_dict(data, 'missions')
    local_sets = get_or_create_dict(missions, 'local_sets')
    
    local_sets['missionset_main_cityepilogue'] = {
        'missions': {
            'mission_main_cityepilogue': {
                'status': 'Active',
                'cursorposition': 8,
                'final': {
                    'inv_openportal_endstate': 'completed',
                    'phasedimensionentered_1st': True,
                    'defeat_arjay_endstate': 'completed',
                    'take_object_endstate': 'completed',
                },
                'objectives': {
                    'entervault': {'status': 'Completed_PostFinished'},
                    'defeat_arjay': {'status': 'Completed_PostFinished'},
                    'entervault_todefeatarjay': {'status': 'Deactivated_PostFinished'},
                    'explore_vault': {'status': 'Completed_PostFinished'},
                    'lootchests': {'status': 'Completed_PostFinished', 'updatecount': 4},
                    'returntomoxxisbar': {'status': 'Completed_Finishing'},
                    'speaktolilith': {'status': 'Completed_PostFinished'},
                    'take_object': {'status': 'Completed_PostFinished'},
                    'inv_readyforspeaktolilith': {'status': 'Completed_PostFinished'},
                    '_lootchests_sub3': {'status': 'Completed_PostFinished'},
                    '_lootchests_sub1': {'status': 'Completed_PostFinished'},
                    '_lootchests_sub2': {'status': 'Completed_PostFinished'},
                    '_lootchests_sub0': {'status': 'Completed_PostFinished'},
                    'inv_playerarrivedatfinalplatform': {'status': 'Completed_PostFinished'},
                    'inv_openportal': {'status': 'Completed_PostFinished'},
                    'inv_interactwithrift': {'status': 'Completed_PostFinished'},
                }
            }
        }
    }

def open_all_vault_doors(data):
    stats = get_or_create_dict(data, 'stats')
    openworld = get_or_create_dict(stats, 'openworld')
    collectibles = get_or_create_dict(openworld, 'collectibles')
    
    for category in ['vaultdoor', 'vaultlock']:
        if category in COLLECTIBLES and isinstance(COLLECTIBLES[category], dict):
             collectibles[category] = copy.deepcopy(COLLECTIBLES[category])

# --- Progression Logic ---

def update_sdu_points(data):
    point_total = 0
    activity_points = 40
    activity_names = [
        'missionset_zoneactivity_crawler',
        'missionset_zoneactivity_drillsite',
        'missionset_zoneactivity_mine',
        'missionset_zoneactivity_orderbunker',
        'missionset_zoneactivity_safehouse',
        'missionset_zoneactivity_silo',
    ]
    
    missions = data.get('missions', {})
    local_sets = missions.get('local_sets', {})
    
    for activity in activity_names:
        ms = local_sets.get(activity, {}).get('missions', {})
        completed_activities = 0
        for m in ms.values():
            if isinstance(m, dict) and m.get('status') == 'completed':
                completed_activities += 1
        point_total += completed_activities * activity_points
        
    collectible_points = {
        'propaspeakers': 20,
        'capsules': 15,
        'evocariums': 15,
        'augurshrines': 10,
        'caches': 10,
        'safes': 10,
        'vaultsymbols': 5,
    }
    
    collectibles = data.get('stats', {}).get('openworld', {}).get('collectibles', {})
    
    for key, points in collectible_points.items():
        if key in collectibles:
            val = collectibles[key]
            if isinstance(val, dict):
                point_total += len(val) * points
            else:
                point_total += points
    
    progression = get_or_create_dict(data, 'progression')
    point_pools = get_or_create_dict(progression, 'point_pools')
    old_total = point_pools.get('echotokenprogresspoints', 0)
    
    if point_total > old_total:
        point_pools['echotokenprogresspoints'] = point_total

def unlock_all_specialization(data):
    state = get_or_create_dict(data, 'state')
    experience = get_or_create_list(state, 'experience')
    
    found = False
    for exp in experience:
        if exp.get('type') == 'Specialization':
            exp['level'] = 701
            exp['points'] = 7431910510
            found = True
            break
    if not found:
        experience.append({'type': 'Specialization', 'level': 701, 'points': 7431910510})
        
    progression = get_or_create_dict(data, 'progression')
    graphs = get_or_create_list(progression, 'graphs')
    
    graph = next((g for g in graphs if g.get('name') == 'ProgressGraph_Specializations'), None)
    if not graph:
        graph = {
            'name': 'ProgressGraph_Specializations',
            'group_def_name': 'progress_group',
            'nodes': []
        }
        graphs.append(graph)
        
    spec_names = [
        'Survivor', 'Artificer', 'Enforcer', 'Slayer',
        'Hunter', 'Adventurer', 'Wanderer'
    ]
    
    # Find group_def_name
    found_group_def = None
    for g in graphs:
        if g.get('group_def_name') and g['group_def_name'] != 'progress_group':
            found_group_def = g['group_def_name']
            break
            
    graph['group_def_name'] = found_group_def or graph.get('group_def_name') or ''
    graph['nodes'] = [{'name': name, 'points_spent': 100} for name in spec_names]
    
    point_pools = get_or_create_dict(progression, 'point_pools')
    point_pools['specializationtokenpool'] = 700
    
    stage_epilogue_mission(data)

def set_character_to_max_level(data):
    set_character_level(data, MAX_LEVEL)

def set_character_level(data, level):
    state = get_or_create_dict(data, 'state')
    experience = get_or_create_list(state, 'experience')
    
    # Placeholder for XP calculation if not available
    # Using a rough approximation or hardcoded values if possible would be better
    # For now, I will assume level 50 has specific XP if MAX_LEVEL is 50, 
    # otherwise I might need the formula.
    # Since calculateCharacterXp is missing, I'll just put a placeholder value or 0
    # However, the JS code says:
    # let xp = typeof CHARACTER_LEVEL_XP === 'object' ... : calculateCharacterXp(level);
    # If I set points to 0, it might be weird.
    # Let's assume level 50 is what user wants mostly.
    # From unlockAllSpecialization we saw huge XP.
    # I will define a simple placeholder xp calculation or just set it to a high number if level 50?
    # No, I should try to be safe.
    
    # NOTE: Assuming a simple linear or exponential curve is risky.
    # I'll just set a dummy value if I can't calculate it, or if level is 50 I can try to guess.
    # But wait, `set_character_to_max_level` is what is used.
    
    xp = 0 # Placeholder. If I had the logic I would put it here.
    
    # Hardcode XP for level 50 based on user feedback
    if level == 50:
        xp = 3430227

    idx = -1
    for i, exp in enumerate(experience):
        if exp.get('type') == 'Character':
            idx = i
            break
    
    if idx != -1:
        experience[idx]['level'] = level
        if xp > 0:
            experience[idx]['points'] = xp

    progression = get_or_create_dict(data, 'progression')
    point_pools = get_or_create_dict(progression, 'point_pools')
    point_pools['characterprogresspoints'] = level - 1

def set_character_class(data, class_key, char_name=None):
    if class_key not in CHARACTER_CLASSES:
        return
    
    info = CHARACTER_CLASSES[class_key]
    if char_name is None:
        char_name = info['name']
        
    state = get_or_create_dict(data, 'state')
    state['class'] = 'Char_' + class_key
    state['char_name'] = char_name
    state['char_guid'] = uuid.uuid4().hex.upper()

def set_max_sdu(data):
    progression = get_or_create_dict(data, 'progression')
    graphs = get_or_create_list(progression, 'graphs')
    point_pools = get_or_create_dict(progression, 'point_pools')
    
    points = [5, 10, 20, 30, 50, 80, 120, 235]
    upgrades = [
        {'prefix': 'Ammo_Pistol', 'levels': 7},
        {'prefix': 'Ammo_SMG', 'levels': 7},
        {'prefix': 'Ammo_AR', 'levels': 7},
        {'prefix': 'Ammo_SG', 'levels': 7},
        {'prefix': 'Ammo_SR', 'levels': 7},
        {'prefix': 'Backpack', 'levels': 8},
        {'prefix': 'Bank', 'levels': 8},
        {'prefix': 'Lost_Loot', 'levels': 8},
    ]
    
    nodes = []
    for u in upgrades:
        for i in range(u['levels']):
            nodes.append({
                'name': f"{u['prefix']}_{str(i+1).zfill(2)}",
                'points_spent': points[i]
            })
            
    sdu_graph = {
        'name': 'sdu_upgrades',
        'group_def_name': 'Oak2_GlobalProgressGraph_Group',
        'nodes': nodes
    }
    
    existing_idx = -1
    for i, g in enumerate(graphs):
        if g.get('name') == 'sdu_upgrades':
            existing_idx = i
            break
            
    if existing_idx != -1:
        graphs[existing_idx] = sdu_graph
    else:
        graphs.append(sdu_graph)
        
    total_points = sum(n.get('points_spent', 0) for n in nodes)
    old_points = point_pools.get('echotokenprogresspoints', 0)
    point_pools['echotokenprogresspoints'] = max(old_points, total_points)

def unlock_all_hover_drives(data):
    unlockables_dict = get_or_create_dict(data, 'unlockables')
    hover_drives = get_or_create_dict(unlockables_dict, 'unlockable_hoverdrives')
    existing = get_or_create_list(hover_drives, 'entries')
    
    # Generate list (from unlockables.js)
    manufacturers = [
        'Borg', 'Daedalus', 'Jakobs', 'Maliwan',
        'Order', 'Tediore', 'Torgue', 'Vladof'
    ]
    new_list = []
    for mfr in manufacturers:
        for i in range(1, 6):
            if mfr == 'Jakobs' and (i == 1 or i == 3):
                new_list.append(f"unlockable_hoverdrives.{mfr.lower()}_{str(i).zfill(2)}")
            else:
                new_list.append(f"unlockable_hoverdrives.{mfr}_{str(i).zfill(2)}")
                
    merged = set(existing)
    for item in new_list:
        merged.add(item)
        
    hover_drives['entries'] = sorted(list(merged), key=lambda x: x.lower())

# --- Challenge Functions ---

def complete_all_challenges(data):
    complete_uvh_challenges(data)
    complete_combat_challenges(data)
    complete_character_challenges(data)
    complete_enemies_challenges(data)
    complete_loot_challenges(data)
    complete_world_challenges(data)
    complete_economy_challenges(data)
    complete_elemental_challenges(data)
    complete_weapon_challenges(data)
    complete_equipment_challenges(data)
    complete_manufacturer_challenges(data)
    complete_licensed_parts_challenges(data)
    complete_phosphene_challenges(data)

def complete_uvh_challenges(data):
    counters = {
        'mission_uvh_1a': 1, 'mission_uvh_1b': 1, 'mission_uvh_1c': 1,
        'mission_uvh_2a': 1, 'mission_uvh_2b': 1, 'mission_uvh_2c': 1, 'mission_uvh_2d': 1,
        'mission_uvh_3a': 1, 'mission_uvh_3b': 1, 'mission_uvh_3c': 1, 'mission_uvh_3d': 1,
        'mission_uvh_4a': 1, 'mission_uvh_4b': 1, 'mission_uvh_4c': 1, 'mission_uvh_4d': 1,
        'mission_uvh_5a': 1, 'mission_uvh_5b': 1, 'mission_uvh_5c': 1,
        'uvh_1_finalchallenge': 1, 'uvh_2_finalchallenge': 1,
        'uvh_3_finalchallenge': 1, 'uvh_4_finalchallenge': 1, 'uvh_5_finalchallenge': 1,
    }
    update_stats_counters(data, counters)

def complete_combat_challenges(data):
    counters = {
        'general_kill_enemies': 8000, 'general_kill_badass': 500, 'general_kill_crit': 2000,
        'repkit_uses': 500, 'general_kill_melee': 2000, 'general_kill_groundpound': 200,
        'general_kill_sliding': 1500, 'general_kill_dashing': 1000, 'general_kill_airborne': 1000,
        'repkit_lifesteal': 900000, 'revivepartner': 200, 'secondwind': 200, 'secondwindbadassboss': 60,
    }
    update_stats_counters(data, counters)

def complete_character_challenges(data):
    counters = {
        'siren_death_tiered': 1000, 'siren_death_single': 1,
        'siren_demonology_tiered': 1000, 'siren_demonology_single': 1,
        'siren_duplicate_tiered': 1000, 'siren_duplicate_single': 1, 'siren_levelup': 50,
        'exo_autolock_tiered': 1000, 'exo_autolock_single': 1,
        'exo_buster_tiered': 1000, 'exo_buster_single': 1,
        'exo_heavyarms_tiered': 1000, 'exo_heavyarms_single': 1, 'exo_levelup': 50,
        'gravitar_terminal_tiered': 1000, 'gravitar_terminal_single': 1,
        'gravitar_stasis_tiered': 1000, 'gravitar_stasis_single': 1,
        'gravitar_exodus_tiered': 1000, 'gravitar_exodus_single': 1, 'gravitar_levelup': 50,
        'paladin_cybernetics_tiered': 1000, 'paladin_cybernetics_single': 1,
        'paladin_vengeance_tiered': 1000, 'paladin_vengeance_single': 1,
        'paladin_weaponmaster_tiered': 1000, 'paladin_weaponmaster_single': 1, 'paladin_levelup': 50,
    }
    update_stats_counters(data, counters)

def complete_enemies_challenges(data):
    counters = {
        'killenemyarmy_bandits': 5000, 'killenemytype_psycho': 1500, 'killenemytype_guntoter': 1250,
        'killenemytype_splice': 750, 'killenemytype_meathead': 300, 'killenemytype_phalanx': 250,
        'killenemyarmy_creatures': 4500, 'killenemytype_cat': 1500, 'killenemytype_bat': 500,
        'killenemytype_beast': 750, 'killenemytype_creep': 750, 'killenemytype_pangolin': 750,
        'killenemytype_thresher': 750, 'killenemyarmy_order': 4000, 'killenemytype_grunt': 1500,
        'killenemytype_soldier': 1500, 'killenemytype_striker': 1500, 'killenemytype_drone': 350,
        'killenemytype_leader': 750, 'killenemytype_brute': 600, 'general_kill_corrupted': 200,
    }
    update_stats_counters(data, counters)

def complete_loot_challenges(data):
    counters = {
        'loot_anylootable': 2500, 'loot_redchest': 250, 'getcash': 3000000, 'geteridium': 10000,
        'loot_whites': 200, 'loot_greens': 200, 'loot_blues': 150, 'loot_purples': 75,
        'loot_legendaries': 25, 'loot_weapons': 500, 'loot_gadgets': 200, 'loot_shields': 200,
        'loot_repkits': 200, 'loot_classmods': 200, 'loot_enhancements': 200,
    }
    update_stats_counters(data, counters)

def complete_world_challenges(data):
    counters = {
        '10_worldevents_colosseum': 1, '11_worldevents_airship': 1,
        '12_worldevents_meteor': 1, '24_missions_side': 98,
    }
    update_stats_counters(data, counters, 'achievements')
    
    stats = get_or_create_dict(data, 'stats')
    openworld = get_or_create_dict(stats, 'openworld')
    misc = get_or_create_dict(openworld, 'misc')
    prev_fish = misc.get('fish')
    if prev_fish is None or prev_fish < 50:
        misc['fish'] = 50

def complete_economy_challenges(data):
    counters = {
        'economy_maxheld_cash': 1, 'economy_maxheld_morecash': 1,
        'economy_upgrade_inventory': 1, 'economy_upgrade_inventory_all': 1,
        'economy_sellloot': 500, 'economy_firmware_set': 1,
    }
    update_stats_counters(data, counters)

def complete_elemental_challenges(data):
    counters = {
        'kill_elemental_fire': 2500, 'kill_elemental_shock': 2000,
        'kill_elemental_corrosive': 1600, 'kill_elemental_radiation': 2500,
        'kill_elemental_cryo': 1000, 'kill_2_status': 5,
    }
    update_stats_counters(data, counters)

def complete_weapon_challenges(data):
    counters = {
        'pistol_kill': 2000, 'pistol_kill_secondwind': 75, 'pistol_hit_crit': 5000,
        'pistol_kill_crit': 750, 'pistol_kill_scoped': 750, 'pistol_kill_gliding': 400,
        'smg_kill': 2000, 'smg_kill_secondwind': 75, 'smg_hit_crit': 10000,
        'smg_kill_crit': 1000, 'smg_kill_dashing': 1500, 'smg_kill_sliding': 750,
        'assault_kill': 2500, 'assault_kill_secondwind': 75, 'assault_hit_crit': 7500,
        'assault_kill_crit': 1000, 'assault_kill_scoped': 1500, 'assault_kill_crouched': 500,
        'shotgun_kill': 2000, 'shotgun_kill_secondwind': 75, 'shotgun_hit_crit': 5000,
        'shotgun_kill_crit': 750, 'shotgun_kill_sliding': 1000, 'shotgun_kill_dashing': 1000,
        'shotgun_kill_close': 1500, 'shotgun_kill_distant': 600, 'shotgun_bigshot': 1,
        'sniper_kill': 2000, 'sniper_kill_secondwind': 75, 'sniper_hit_crit': 4500,
        'sniper_kill_crit': 750, 'sniper_kill_distant': 1000, 'sniper_kill_oneshot': 150,
        'sniper_kill_unaware': 300, 'sniper_kill_unscoped': 200, 'sniper_bigshot': 1,
    }
    update_stats_counters(data, counters)

def complete_equipment_challenges(data):
    counters = {
        'killenemy_grenade': 1000, 'killenemy_grenade_multikill': 300,
        'killenemy_grenade_mirv': 400, 'killenemy_grenade_artillery': 450,
        'killenemy_grenade_lingering': 300, 'killenemy_grenade_singularity': 500,
        'killenemy_grenade_amp': 300,
        'shield_take_damage': 2000000, 'shield_kills': 750, 'shield_pickup_boosters': 1000,
        'shield_pickup_shards': 1000, 'shield_kills_nova': 200, 'shield_kills_reflect': 200,
        'shield_absorb_ammo': 5000, 'shield_kills_amp': 500,
        'killenemy_heavy_vladof': 250, 'killenemy_heavy_vladof_multikill': 100,
        'killenemy_heavy_maliwan': 350, 'killenemy_heavy_maliwan_bigshot': 1,
        'killenemy_heavy_torgue': 300, 'killenemy_heavy_torgue_directhit': 100,
        'killenemy_heavy_borg': 400, 'killenemy_heavy_borg_multikill': 100,
        'repkit_healself': 400000, 'repkit_kills': 250, 'repkit_healothers': 400000,
    }
    update_stats_counters(data, counters)

def complete_manufacturer_challenges(data):
    counters = {
        'manufacturer_jakobs_kills': 2000, 'manufacturer_jakobs_underbarrel_kills': 175,
        'manufacturer_jakobs_ricochetkills': 150, 'manufacturer_jakobs_oneshot': 500,
        'manufacturer_jakobs_quickdraw': 350, 'manufacturer_jakobs_grenadecrits': 400,
        'manufacturer_daedalus_kills': 2000, 'manufacturer_daedalus_underbarrel_kills': 150,
        'manufacturer_daedalus_multiloader_pistol': 500, 'manufacturer_daedalus_multiloader_smg': 750,
        'manufacturer_daedalus_multiloader_assault': 600, 'manufacturer_daedalus_multiloader_shotgun': 400,
        'manufacturer_daedalus_multiloader_sniper': 400,
        'manufacturer_vladof_kills': 2000, 'manufacturer_vladof_extrabarrel': 750,
        'manufacturer_vladof_explosive_underbarrel': 175, 'manufacturer_vladof_bipod': 750,
        'manufacturer_vladof_shotgun_underbarrel': 150,
        'manufacturer_maliwan_kills': 2000, 'manufacturer_maliwan_underbarrel_kills': 175,
        'manufacturer_maliwan_status_fire': 750, 'manufacturer_maliwan_status_shock': 750,
        'manufacturer_maliwan_status_corrosive': 400, 'manufacturer_maliwan_status_radiation': 400,
        'manufacturer_maliwan_status_cryo': 750,
        'manufacturer_tediore_kills': 1500, 'manufacturer_tediore_underbarrel_kills': 150,
        'manufacturer_tediore_emptyreload_kills': 750, 'manufacturer_tediore_fullreload_kills': 600,
        'manufacturer_tediore_comboreload_kills': 200, 'manufacturer_tediore_turret_kills': 500,
        'manufacturer_torgue_kills': 1300, 'manufacturer_torgue_underbarrel_kills': 125,
        'manufacturer_torgue_splash_kills': 600, 'manufacturer_torgue_sticky_kills': 750,
        'manufacturer_torgue_impact_kills': 750, 'manufacturer_torgue_grenade_kills': 400,
        'manufacturer_borg_kills': 1300, 'manufacturer_borg_underbarrel_kills': 125,
        'manufacturer_borg_criticalhits': 1500, 'manufacturer_borg_multikills': 450,
        'manufacturer_order_kills': 1500, 'manufacturer_order_underbarrel_kills': 125,
        'manufacturer_order_halfcharge_kills': 600, 'manufacturer_order_fullcharge_kills': 750,
        'manufacturer_order_oneshot_kills': 500, 'manufacturer_order_killorder': 750,
    }
    update_stats_counters(data, counters)

def complete_licensed_parts_challenges(data):
    counters = {
        'spareparts_atlas_tracker_pucks': 350, 'spareparts_atlas_tracker_grenades': 600,
        'spareparts_cov_overheated': 250, 'spareparts_cov_not_overheated': 600,
        'spareparts_hyperion_amp_shield': 150, 'spareparts_hyperion_absorb_ammo': 3000,
        'spareparts_hyperion_reflect_shield': 100,
    }
    update_stats_counters(data, counters)

def complete_phosphene_challenges(data):
    counters = {
        'base': {
            'shiny_anarchy': 1, 'shiny_asher': 1, 'shiny_atlien': 1, 'shiny_ballista': 1,
            'shiny_beegun': 1, 'shiny_bloodstarved': 1, 'shiny_bod': 1, 'shiny_bonnieclyde': 1,
            'shiny_boomslang': 1, 'shiny_bugbear': 1, 'shiny_bully': 1, 'shiny_chuck': 1,
            'shiny_coldshoulder': 1, 'shiny_commbd': 1, 'shiny_complex_root': 1,
            'shiny_conglomerate': 1, 'shiny_convergence': 1, 'shiny_crowdsourced': 1,
            'shiny_dividedfocus': 1, 'shiny_dualdamage': 1, 'shiny_finnty': 1, 'shiny_fisheye': 1,
            'shiny_gmr': 1, 'shiny_goalkeeper': 1, 'shiny_goldengod': 1, 'shiny_goremaster': 1,
            'shiny_heartgun': 1, 'shiny_heavyturret': 1, 'shiny_hellfire': 1, 'shiny_hellwalker': 1,
            'shiny_kaleidosplode': 1, 'shiny_kaoson': 1, 'shiny_katagawa': 1,
            'shiny_kickballer': 1, 'shiny_kingsgambit': 1, 'shiny_leadballoon': 1,
            'shiny_linebacker': 1, 'Shiny_Loarmaster': 1, 'shiny_lucian': 1, 'shiny_lumberjack': 1,
            'shiny_luty': 1, 'shiny_noisycricket': 1, 'shiny_ohmigot': 1, 'shiny_om': 1,
            'shiny_onslaught': 1, 'shiny_phantom_flame': 1, 'shiny_plasmacoil': 1,
            'shiny_potatothrower': 1, 'shiny_prince': 1, 'shiny_queensrest': 1, 'shiny_quickdraw': 1,
            'shiny_rainbowvomit': 1, 'shiny_rangefinder': 1, 'shiny_roach': 1, 'shiny_rocketreload': 1,
            'shiny_rowan': 1, 'shiny_rubysgrasp': 1, 'shiny_seventh_sense': 1, 'shiny_sideshow': 1,
            'shiny_slugger': 1, 'shiny_star_helix': 1, 'shiny_stopgap': 1, 'shiny_stray': 1,
            'shiny_sweet_embrace': 1, 'shiny_symmetry': 1, 'shiny_tkswave': 1, 'shiny_truck': 1,
            'Shiny_Ultimate': 1, 'shiny_vamoose': 1, 'shiny_wf': 1, 'shiny_wombocombo': 1,
            'shiny_zipgun': 1,
        }
    }
    update_stats_counters(data, counters, 'shinygear')

def complete_all_achievements(data):
    counters = {
        '00_level_10': 1, '01_level_30': 1, '02_level_50': 1, '03_uvh_5': 1,
        '04_cosmetics_collect': 60, '05_vehicles_collect': 10, '06_legendaries_equip': 1,
        '07_challenges_gear': 1, '08_challenges_manufacturer': 1,
        '10_worldevents_colosseum': 1, '11_worldevents_airship': 1, '12_worldevents_meteor': 1,
        '13_contracts_complete': 80, '14_discovery_grasslands': 54, '15_discovery_mountains': 62,
        '16_discovery_shatteredlands': 47, '17_discovery_city': 21, '18_worldboss_defeat': 1,
        '19_vaultguardian_defeat': {
            '19_vaultguardian_grasslands': 1,
            '19_vaultguardian_mountains': 1,
            '19_vaultguardian_shatteredlands': 1,
        },
        '20_missions_survivalist': 3, '21_missions_auger': 7, '22_missions_electi': 3,
        '23_missions_claptrap': 5, '24_missions_side': 98, '25_missions_grasslands': 1,
        '26_missions_mountains': 1, '27_missions_shatteredlands': 1, '28_missions_elpis': 1,
        '29_missions_main': 1, '30_moxxi_hidden': 1, '31_tannis_hidden': 1,
        '32_zane_hidden': 1, '33_oddman_hidden': 1, '34_dave_hidden': 1,
    }
    update_stats_counters(data, counters, 'achievements')
    merge_missionsets_with_prefix(data, 'missionset_zoneactivity_')

def complete_discovery_achievements(data):
    counters = {
        '14_discovery_grasslands': 54,
        '15_discovery_mountains': 62,
        '16_discovery_shatteredlands': 47,
        '17_discovery_city': 21,
    }
    update_stats_counters(data, counters, 'achievements')

def max_currency(data):
    state = get_or_create_dict(data, 'state')
    currencies = get_or_create_dict(state, 'currencies')
    currencies['cash'] = 2147483647
    currencies['eridium'] = 2147483647

def max_ammo(data):
    state = get_or_create_dict(data, 'state')
    state['ammo'] = {
        'assaultrifle': 1260,
        'pistol': 900,
        'shotgun': 220,
        'smg': 1620,
        'sniper': 190,
        'repkit': 10,
    }
