# Borderlands 4 Save Editor

[Click here for Chinese Version README (中文版)](README_CN.md)

<h1 align="center">Borderlands 4 Save Editor</h1>
<p align="center"><b>By SuperExboom</b></p>

---

### Introduction
This is a powerful save editor for Borderlands 4, designed to provide comprehensive save editing capabilities. It is completely free and supports both English and Chinese languages.
This tool allows you to modify character data, manage inventory items, unlock game content, instantly generate and customize gear, and provides powerful code conversion and generation features.

---

### Features

#### Save Management
- Automatically scans game save directories.
- Supports 64-bit ID decryption and encryption for Steam and Epic platforms.
- Supports opening, saving, and "save as" for `.sav` files.
- Automatically backs up original save files.

#### Character Editing
- Modify character name and current class.
- Customize difficulty settings.
- Edit Character Level and Experience Points (XP).
- Edit Spec Level and Spec Points.
- Edit Money and Eridium.
- One-click synchronization of all backpack item levels to the current character level.

#### Unlocks & Presets
Provides various one-click unlock functions:
- Remove map fog, discover all locations, unlock all safehouses.
- Unlock all collectibles, complete all challenges, complete all achievements.
- Skip story missions, skip all missions.
- One-click Max Level (Level 50), Max SDU (Storage Deck Upgrades).
- Unlock Vault gates, unlock all vehicles, unlock all specializations, unlock UVHM mode.
- Unlock/Max Everything.

#### Items & Backpack
- View and manage items in your backpack.
- Set Item Flags (Common, Favorite, Junk, Groups 1-4).
- Directly add items to backpack using Base85 codes or decoded format.
- Read items from backpack for modification or copy their serial numbers.

#### Gear Generation & Editing
Features dedicated tabs for deep customization of various gear types:
- **Weapon Editor**: Modify parts, skins, elements, anointments, etc., of existing weapons.
- **Weapon Generator**: Generate custom weapons from scratch.
- **Class Mod**: Customize class, rarity, skill bonuses, and passive perks.
- **Enhancement**: Customize manufacturer, rarity, and perk stacking.
- **Grenade**: Customize manufacturer, level, rarity, perks, elements, fuses, etc.
- **Shield**: Customize manufacturer, level, rarity, shield type (Energy/Armor), and perks.
- **Repkit**: Customize prefix, resistances, firmware, and perks.
- **Heavy Weapon**: Customize barrel, element, firmware, attachments, etc.
- All generators support direct "Add to Backpack" or "Copy Serial".

#### Converter & Advanced Tools
- **Code Converter**: Supports conversion between Base85 encoding and Deserialized data.
- **Batch Processing**: Batch convert codes and batch import lists of codes into the backpack.
- **Iterator Generator**: Supports batch generating item sequences by setting value ranges (e.g., generating all skins, iterating through all part combinations).
- **YAML Editor**: Provides tree view and text view to directly edit the raw YAML data structure of the save file, suitable for advanced users.

---

### How to Build

If you want to build the executable (`.exe`) from source, please ensure you have Python installed and run the `pyinstaller_config.py` script located in the project root directory.

This script will automatically handle dependencies, collect required resource files (such as images, JSONs, CSVs, etc.), and invoke PyInstaller to generate `dist/BL4SaveEditor.exe`.

**Steps:**

1.  Install dependencies:
    ```bash
    pip install pyinstaller pillow pyyaml pycryptodome PyQt6 pandas
    ```
2.  Run the build script:
    ```bash
    python pyinstaller_config.py
    ```
3.  Once the script finishes, the generated executable will be located in the `dist` folder.

---

### Instructions
1. Launch the software; it will automatically scan default save locations.
2. Select a save file and enter the corresponding 64-bit ID if prompted (usually auto-detected; if manual input is required, enter your Steam ID or Epic ID).
3. Once loaded, you can make modifications across the various tabs.
4. Detailed features are organized by tabs (Character, Items, Weapon Editor, etc.).
5. Click "Save" to apply changes.
6. It is recommended to manually backup your save files before editing, although the software creates automatic backups.

---

### Notes
- Please do not use modified illegal items in online multiplayer to ruin other players' experience.
- This software is completely free. Do NOT pay for it.

---

### Special Thanks
- **@Nicnl** and **@InflamedSebi** - For Base85 deserialize huge work
- **@Whiteshark-2022** and **@Mattmab** - For Class mods icon, Enhancement UI design and data
- **@THATDONFC** - For Weapon builder UI design
