"""Core package with compatible lazy exports."""

from importlib import import_module


_CLASSES = {
    "SaveGameController": ("save_game_controller", "SaveGameController"),
    "infer_user_id_from_save_path": ("save_game_controller", "infer_user_id_from_save_path"),
    "SaveSelectorWidget": ("save_selector_widget", "SaveSelectorWidget"),
    "ThemeManager": ("theme_manager", "ThemeManager"),
}
_MODULES = {
    "b_encoder", "bl4_functions", "decoder_logic", "lookup", "resource_loader",
    "unlock_data", "unlock_logic", "item_display_resolver", "serial_inspect",
    "weapon_display_stats", "equipment_display_stats", "card_image",
}

__all__ = list(_CLASSES) + sorted(_MODULES)


def __getattr__(name):
    if name in _MODULES:
        value = import_module(f"{__name__}.{name}")
    else:
        try:
            module_name, attr_name = _CLASSES[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
        value = getattr(import_module(f"{__name__}.{module_name}"), attr_name)
    globals()[name] = value
    return value
