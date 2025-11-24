import ast
import json
from pathlib import Path

def extract_strings_from_data(data):
    strings_to_localize = {}

    # Manufacturers
    for mfg_key, mfg_data in data.get('manufacturers', {}).items():
        name = mfg_data.get('name')
        if name:
            strings_to_localize[name] = name

        # Perks
        for perk in mfg_data.get('perks', []):
            perk_name = perk.get('name')
            if perk_name:
                strings_to_localize[perk_name] = perk_name

    # Rarity names (from the keys of rarity_map_247)
    for rarity_name in data.get('rarity_map_247', {}).keys():
        strings_to_localize[rarity_name] = rarity_name

    # Secondary Stats (247)
    for stat in data.get('secondary_247', []):
        stat_name = stat.get('name')
        if stat_name:
            strings_to_localize[stat_name] = stat_name

    return strings_to_localize

def main():
    try:
        # Read the data file
        data_path = Path('enchancement') / 'enchancement_data.txt'
        with open(data_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Safely evaluate the string to a dictionary
        data = ast.literal_eval(content)
        
        # Extract strings
        localizable_strings = extract_strings_from_data(data)
        
        # Define output path
        output_path = Path('enchancement') / 'localization_zh-CN.json'
        
        # Write to JSON file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(localizable_strings, f, ensure_ascii=False, indent=4)
            
        print(f"Successfully created localization file at: {output_path}")
        print(f"Total strings extracted: {len(localizable_strings)}")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
