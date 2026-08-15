"""Qt tabs with lazy package exports.

Importing :mod:`tabs` used to import every editor, pandas and the 31 MB item
index before the main window existed.  Keep the public names compatible while
loading each module only when its class is actually requested.
"""

from importlib import import_module


_EXPORTS = {
    "QtCharacterTab": ("qt_character_tab", "QtCharacterTab"),
    "QtItemsTab": ("qt_items_tab", "QtItemsTab"),
    "QtConverterTab": ("qt_converter_tab", "QtConverterTab"),
    "QtSerialInspectorTab": ("qt_serial_inspector_tab", "QtSerialInspectorTab"),
    "QtYamlEditorTab": ("qt_yaml_editor_tab", "QtYamlEditorTab"),
    "QtClassModEditorTab": ("qt_class_mod_editor_tab", "QtClassModEditorTab"),
    "QtEnhancementEditorTab": ("qt_enhancement_editor_tab", "QtEnhancementEditorTab"),
    "WeaponEditorTab": ("qt_weapon_editor_tab", "WeaponEditorTab"),
    "QtWeaponGeneratorTab": ("qt_weapon_generator_tab", "QtWeaponGeneratorTab"),
    "QtGodRollTab": ("qt_god_roll_tab", "QtGodRollTab"),
    "QtGrenadeEditorTab": ("qt_grenade_editor_tab", "QtGrenadeEditorTab"),
    "QtShieldEditorTab": ("qt_shield_editor_tab", "QtShieldEditorTab"),
    "QtRepkitEditorTab": ("qt_repkit_editor_tab", "QtRepkitEditorTab"),
    "QtHeavyWeaponEditorTab": ("qt_heavy_weapon_editor_tab", "QtHeavyWeaponEditorTab"),
    "QtLoadoutManagerTab": ("qt_loadout_manager_tab", "QtLoadoutManagerTab"),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    try:
        module_name, class_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(f"{__name__}.{module_name}"), class_name)
    globals()[name] = value
    return value
