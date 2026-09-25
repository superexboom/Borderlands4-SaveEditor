"""角色页视图模型：移植 QtCharacterTab 的全部非渲染逻辑。

离线：角色信息/货币字段编辑与写回、等级↔XP 换算、解锁预设、同步背包等级。
联机：live 运行时面板的状态模型（开关/数值/书签/失物），动作经
app.runtime_action 发出；live 状态由 AppBridge 通过 apply_runtime_state 推入。
"""

from __future__ import annotations

import json
from typing import Any

from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot

from core.unlock_data import CHARACTER_CLASSES, VAULT_CARD_TOKENS
from tabs.qt_character_tab import calc_xp_for_level, calc_xp_for_specialization_level

from .base import PageViewModel, register

# 主线开关动作 → live state 特征键
TOGGLE_FEATURES = {
    "toggle_no_spread": "no_spread", "toggle_no_recoil": "no_recoil",
    "toggle_instant_reload": "instant_reload", "toggle_no_overheat": "no_overheat",
    "toggle_health_lock": "health_lock", "toggle_shield_lock": "shield_lock",
    "toggle_repairkit_no_cd": "repairkit_no_cd", "toggle_skill_no_cd": "skill_no_cd",
    "toggle_gadget_no_cd": "gadget_no_cd", "toggle_stamina_lock": "stamina_lock",
    "toggle_guaranteed_crit": "guaranteed_crit",
    "toggle_dedicated_drop_100": "dedicated_drop_100",
    "toggle_infinite_jump": "infinite_jump",
}

WORLD_PRESETS = (
    ("clear_fog", "clear_map_fog"), ("discover_locs", "discover_all_locations"),
    ("unlock_safehouses", "complete_all_safehouse_missions"),
    ("unlock_collectibles", "complete_all_collectibles"),
    ("unlock_cosmetics", "unlock_all_cosmetics"), ("max_sdu", "set_max_sdu"),
    ("unlock_vault", "unlock_vault_powers"), ("unlock_vehicles", "unlock_all_hover_drives"),
    ("unlock_vault_cards", "unlock_all_vault_card_rewards"),
)
CHAR_PRESETS = (
    ("change_class", "change_class_popup"), ("max_level", "set_character_to_max_level"),
    ("complete_challenges", "complete_all_challenges"),
    ("complete_achievements", "complete_all_achievements"),
    ("skip_story", "complete_all_story_missions"), ("skip_all", "complete_all_missions"),
    ("unlock_specs", "unlock_all_specialization"), ("unlock_uvhm", "unlock_postgame"),
    ("max_ammo", "max_ammo"),
)

# live 面板布局描述（label_key, action）；toggles 与按钮的分区与主线一致
LIVE_SECTIONS = (
    ("live_survival", (
        ("toggle_health_lock", "toggle_health_lock"),
        ("toggle_shield_lock", "toggle_shield_lock"),
        ("toggle_demigod", "toggle_demigod"),
        ("toggle_stamina_lock", "toggle_stamina_lock"),
    )),
    ("live_weapon", (
        ("toggle_infinite_ammo", "toggle_infinite_ammo"),
        ("refill_ammo", "refill_ammo"),
        ("toggle_instant_reload", "toggle_instant_reload"),
        ("toggle_no_overheat", "toggle_no_overheat"),
        ("toggle_no_spread", "toggle_no_spread"),
        ("toggle_no_recoil", "toggle_no_recoil"),
        ("toggle_guaranteed_crit", "toggle_guaranteed_crit"),
    )),
    ("live_cooldown", (
        ("toggle_repairkit_no_cd", "toggle_repairkit_no_cd"),
        ("toggle_skill_no_cd", "toggle_skill_no_cd"),
        ("toggle_gadget_no_cd", "toggle_gadget_no_cd"),
    )),
    ("live_progress", (
        ("max_money", "max_currency"),
        ("max_eridium", "max_eridium"),
        ("max_level", "max_level"),
        ("max_specialization", "max_specialization"),
        ("max_sdu_tokens", "max_sdu_tokens"),
        ("toggle_infinite_jump", "toggle_infinite_jump"),
    )),
    ("live_loot", (
        ("toggle_dedicated_drop_100", "toggle_dedicated_drop_100"),
        ("rarity_legendary", "rarity_legendary"),
        ("rarity_pearlescent", "rarity_pearlescent"),
        ("rarity_reset", "rarity_reset"),
        ("reset_runtime_modifiers", "reset_runtime_modifiers"),
    )),
)

LIVE_TUNING = (
    ("fire_rate_scale", "set_fire_rate", (1, 2, 5, 10, 20)),
    ("movement_speed_scale", "set_movement_speed", (1, 1.5, 2, 3, 5, 10)),
    ("jump_height_scale", "set_jump_height", (1, 1.5, 2, 3, 5, 10)),
    ("critical_damage_scale", "set_critical_damage", (1, 2, 5, 10, 20, 50)),
    ("experience_reward_scale", "set_experience_multiplier", (1, 2, 3, 5, 10)),
    ("cash_reward_scale", "set_cash_multiplier", (1, 2, 3, 5, 10)),
    ("eridium_reward_scale", "set_eridium_multiplier", (1, 2, 3, 5, 10)),
    ("dedicated_drop_multiplier", "set_dedicated_drop_multiplier", tuple(range(1, 11))),
)


@register("character", "CharacterPage.qml")
class CharacterViewModel(PageViewModel):
    STRINGS_SECTION = "character_tab"

    dataChanged = pyqtSignal()
    runtimeStateChanged = pyqtSignal()
    xpChanged = pyqtSignal()

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self._fields: dict[str, str] = {}
        self._cur_paths: dict[str, Any] = {}
        self._is_profile = False
        self._live_state: dict[str, Any] = {}
        self._runtime_busy = False
        self._runtime_status = ""
        self._runtime_status_ok = True
        self._inventory_mutation_blocked = False
        self._bookmarks: list[dict[str, Any]] = self._load_bookmarks()
        app.liveChanged.connect(self._on_live_changed)

    # ------------------------------------------------------------------
    # 通用
    # ------------------------------------------------------------------
    def _on_live_changed(self) -> None:
        self.dataChanged.emit()

    @pyqtProperty(bool, notify=dataChanged)
    def liveMode(self) -> bool:
        return self.app.liveActive

    @pyqtProperty(bool, notify=dataChanged)
    def saveLoaded(self) -> bool:
        return self.app.saveLoaded

    @pyqtProperty(bool, notify=dataChanged)
    def isProfileSave(self) -> bool:
        return self._is_profile

    @pyqtProperty(str, notify=dataChanged)
    def presetModeHint(self) -> str:
        labels = self.strings.get("labels", {})
        key = "preset_mode_profile" if self._is_profile else "preset_mode_character"
        text = labels.get(key, "")
        credit = labels.get("preset_credit", "").strip()
        return f"{text}\n{credit}" if credit else text

    # ------------------------------------------------------------------
    # 离线字段
    # ------------------------------------------------------------------
    @pyqtProperty("QVariantMap", notify=dataChanged)
    def fields(self) -> dict[str, str]:
        return self._fields

    @pyqtProperty(list, notify=dataChanged)
    def vaultCurrencies(self) -> list[dict[str, str]]:
        labels = self.strings.get("labels", {})
        result = []
        for card in VAULT_CARD_TOKENS:
            if not isinstance(card, dict) or not isinstance(card.get("currency_key"), str):
                continue
            key = card["currency_key"]
            number = card.get("number", card.get("card_id", ""))
            label = labels.get("vault_card_tokens", "Vault Card {number} Tokens:").format(number=number)
            result.append({"key": key, "label": label, "value": self._fields.get(key, "")})
        return result

    @pyqtProperty(str, notify=xpChanged)
    def xpValue(self) -> str:
        return self._fields.get("角色经验值", "")

    @pyqtProperty(str, notify=xpChanged)
    def specializationXpValue(self) -> str:
        """Computed specialization XP shown in the locked companion field."""
        return self._fields.get("专精点数", "")

    @pyqtSlot(str, str)
    def setField(self, key: str, value: str) -> None:
        # 编辑过程不发 dataChanged（避免输入框被回写、光标跳动）；
        # 仅等级变化联动重算 XP 并通知 XP 显示。
        self._fields[key] = value
        if key == "角色等级":
            try:
                level = max(1, int(value.strip()))
                self._fields["角色经验值"] = str(calc_xp_for_level(level))
            except ValueError:
                pass
            self.xpChanged.emit()
        elif key == "专精等级":
            try:
                level = max(1, int(value.strip()))
                self._fields["专精点数"] = str(calc_xp_for_specialization_level(level))
            except ValueError:
                pass
            self.xpChanged.emit()

    @pyqtSlot()
    def applyChanges(self) -> None:
        if not self.controller.yaml_obj:
            return
        data = {k: v for k, v in self._fields.items()}
        if self.controller.apply_character_data(data, self._cur_paths):
            self.app.toast(self.tr("main_window.dialogs.char_applied"), "success")
            self.app._mark_all_stale()
            self._stale = False
            self.refresh()
        else:
            self.app.toast(self.tr("main_window.dialogs.char_apply_error"), "error")

    @pyqtSlot()
    def syncLevels(self) -> None:
        if not self.controller.yaml_obj:
            return

        def _do(accepted: bool) -> None:
            if not accepted:
                return
            success, fail, info = self.controller.sync_inventory_levels()
            msg = self.tr("main_window.dialogs.sync_msg").format(success=success, fail=fail)
            if fail > 0:
                details = "\n".join(info)
                msg += self.tr("main_window.dialogs.sync_fail_details").format(details=details)
                self.app.toast(msg, "warning")
            else:
                self.app.toast(msg, "success")
            if success > 0:
                self.app._mark_all_stale()
                self._stale = False
                self.refresh()

        self.app._request_confirm(
            self.tr("main_window.dialogs.warning"),
            self.tr("main_window.dialogs.confirm_sync"),
            _do, warning=True)

    # ------------------------------------------------------------------
    # 解锁预设
    # ------------------------------------------------------------------
    @pyqtProperty(list, notify=dataChanged)
    def worldPresets(self) -> list[dict[str, Any]]:
        presets = self.strings.get("presets", {})
        return [{"key": key, "label": presets.get(key, key), "action": action,
                 "enabled": self._is_profile and not self.liveMode}
                for key, action in WORLD_PRESETS]

    @pyqtProperty(list, notify=dataChanged)
    def charPresets(self) -> list[dict[str, Any]]:
        presets = self.strings.get("presets", {})
        return [{"key": key, "label": presets.get(key, key), "action": action,
                 "enabled": not self._is_profile and not self.liveMode}
                for key, action in CHAR_PRESETS]

    @pyqtSlot(str)
    def unlockPreset(self, action: str) -> None:
        if action == "change_class_popup":
            return  # QML 改走 classOptions + changeClass
        if not self.controller.yaml_obj:
            self.app.toast(self.tr("main_window.dialogs.load_save_first"), "warning")
            return
        if self.controller.apply_unlock_preset(action, {}):
            self.app.toast(self.tr("main_window.dialogs.preset_applied").format(name=action), "success")
            self.app._mark_all_stale()
            self._stale = False
            self.refresh()
        else:
            self.app.toast(self.tr("main_window.dialogs.preset_fail").format(name=action), "error")

    @pyqtProperty(list, notify=dataChanged)
    def classOptions(self) -> list[dict[str, str]]:
        return [{"key": key, "label": f"{info['class']} ({info['name']})"}
                for key, info in CHARACTER_CLASSES.items()]

    @pyqtSlot(str)
    def changeClass(self, class_key: str) -> None:
        if self._is_profile or not self.controller.yaml_obj:
            return
        if self.controller.apply_unlock_preset("set_character_class", {"class_key": class_key}):
            self.app.toast(self.tr("main_window.dialogs.preset_applied").format(
                name="set_character_class"), "success")
            self.app._mark_all_stale()
            self._stale = False
            self.refresh()
        else:
            self.app.toast(self.tr("main_window.dialogs.preset_fail").format(
                name="set_character_class"), "error")

    # ------------------------------------------------------------------
    # 数据填充
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        data = self.controller.get_character_data() or {}
        self._is_profile = bool(data.get("is_profile_save", False))
        self._cur_paths = data.get("cur_paths", {}) or {}
        fields = {}
        for key in ("名称", "难度", "角色等级", "角色经验值", "专精等级", "专精点数", "金钱", "镒矿"):
            fields[key] = str(data.get(key, "") or "")
        for card in VAULT_CARD_TOKENS:
            if isinstance(card, dict) and isinstance(card.get("currency_key"), str):
                fields[card["currency_key"]] = str(data.get(card["currency_key"], "") or "")
        self._fields = fields
        self.dataChanged.emit()
        # 两个经验值只读框是 xpChanged 驱动的声明式绑定，重载数据时也要通知
        self.xpChanged.emit()

    # ------------------------------------------------------------------
    # live 运行时面板
    # ------------------------------------------------------------------
    @pyqtProperty("QVariantMap", notify=runtimeStateChanged)
    def liveState(self) -> dict[str, Any]:
        return self._live_state

    @pyqtProperty(bool, notify=runtimeStateChanged)
    def runtimeBusy(self) -> bool:
        return self._runtime_busy

    @pyqtProperty(str, notify=runtimeStateChanged)
    def runtimeStatus(self) -> str:
        labels = self.strings.get("labels", {})
        return self._runtime_status or labels.get("live_runtime_idle", "Ready.")

    @pyqtProperty(bool, notify=runtimeStateChanged)
    def runtimeStatusOk(self) -> bool:
        return self._runtime_status_ok

    @pyqtProperty(list, notify=runtimeStateChanged)
    def liveSections(self) -> list[dict[str, Any]]:
        labels = self.strings.get("labels", {})
        buttons = self.strings.get("buttons", {})
        sections = []
        for section_key, actions in LIVE_SECTIONS:
            items = []
            for label_key, action in actions:
                items.append({
                    "action": action,
                    "label": buttons.get(label_key, label_key),
                    "checkable": action in TOGGLE_FEATURES,
                    "checked": bool(self._live_state.get(TOGGLE_FEATURES.get(action, ""), False)),
                })
            sections.append({"key": section_key,
                             "title": labels.get(section_key, section_key),
                             "buttons": items})
        return sections

    @pyqtProperty(list, notify=runtimeStateChanged)
    def liveTuning(self) -> list[dict[str, Any]]:
        labels = self.strings.get("labels", {})
        rows = []
        for label_key, action, values in LIVE_TUNING:
            current = float(self._live_state.get(label_key, 1.0) or 1.0)
            rows.append({
                "action": action,
                "label": labels.get(label_key, label_key),
                "options": [{"label": f"{v:g}x", "value": v} for v in values],
                "value": current,
            })
        return rows

    @pyqtSlot(str)
    def runAction(self, action: str) -> None:
        if action in ("set_fov", "reset_fov", "set_base_fov", "set_viewmodel_fov"):
            return
        self.app.runtime_action(action, {})

    @pyqtSlot(str, bool)
    def runToggle(self, action: str, checked: bool) -> None:
        self.app.runtime_action(action, {"enabled": bool(checked)})

    @pyqtSlot(str, "QVariant")
    def runActionWithValue(self, action: str, value: Any) -> None:
        if action in ("set_fov", "reset_fov", "set_base_fov", "set_viewmodel_fov"):
            return
        if action in ("set_fire_rate", "set_movement_speed", "set_jump_height",
                      "set_critical_damage", "set_experience_multiplier",
                      "set_cash_multiplier", "set_eridium_multiplier",
                      "set_dedicated_drop_multiplier", "set_backpack_size",
                      "set_bank_size", "set_magazine_capacity_scale",
                      "set_projectile_speed_scale"):
            self.app.runtime_action(action, {"value": value})
        else:
            self.app.runtime_action(action, {"value": value})

    # -- live 资源行 ------------------------------------------------------
    @pyqtProperty(list, notify=runtimeStateChanged)
    def liveVaultCards(self) -> list[dict[str, Any]]:
        labels = self.strings.get("labels", {})
        result = []
        for card in self._live_state.get("vault_cards") or []:
            if not isinstance(card, dict):
                continue
            name = self._friendly_resource_name(card.get("name") or card.get("token") or str(card.get("track", "")))
            level = int(card.get("level", 0) or 0)
            result.append({
                "label": labels.get("live_vault_card_item", "{name} · Lv{level}").format(name=name, level=level),
                "track": card.get("track"), "token": card.get("token"), "level": level,
            })
        return result

    @pyqtProperty(list, notify=runtimeStateChanged)
    def liveCurrencies(self) -> list[dict[str, Any]]:
        labels = self.strings.get("labels", {})
        result = []
        for currency in self._live_state.get("currencies") or []:
            if not isinstance(currency, dict):
                continue
            name = self._friendly_resource_name(currency.get("name") or currency.get("token") or "")
            amount = int(currency.get("amount", 0) or 0)
            result.append({
                "label": labels.get("live_currency_item", "{name} · {amount}").format(
                    name=name, amount=f"{amount:,}"),
                "token": currency.get("token"), "kind": currency.get("kind") or currency.get("currency"),
            })
        return result

    def _friendly_resource_name(self, value: Any) -> str:
        import re
        labels = self.strings.get("labels", {})
        name = str(value or "").strip()
        match = re.search(r"VaultCard0*(\d+)_(?:Experience|Tokens)$", name, re.IGNORECASE)
        if match:
            return labels.get("vault_card_name", "Vault Card {number}").format(number=int(match.group(1)))
        normalized = re.sub(r"[^a-z0-9]+", "", name.casefold())
        if normalized in {"cash", "money", "currencycash"}:
            return labels.get("live_currency_cash", "Cash")
        if normalized in {"eridium", "eridiumcurrency", "currencyeridium"}:
            return labels.get("live_currency_eridium", "Eridium")
        return name

    @pyqtSlot(int, int)
    def setVaultCardLevel(self, index: int, level: int) -> None:
        cards = self.liveVaultCards
        if not 0 <= index < len(cards):
            return
        card = cards[index]
        params: dict[str, Any] = {"level": int(level)}
        if card.get("track") is not None:
            params["track"] = int(card["track"])
        elif card.get("token"):
            params["token"] = str(card["token"])
        else:
            return
        self.app.runtime_action("set_vault_card_level", params)

    @pyqtSlot(int, int)
    def giveCurrency(self, index: int, amount: int) -> None:
        currencies = self.liveCurrencies
        if not 0 <= index < len(currencies):
            return
        currency = currencies[index]
        params: dict[str, Any] = {"amount": int(amount)}
        if currency.get("token"):
            params["token"] = str(currency["token"])
        elif currency.get("kind"):
            params["kind"] = str(currency["kind"])
        else:
            return
        self.app.runtime_action("give_currency", params)

    # -- live 位置书签 -----------------------------------------------------
    def _load_bookmarks(self) -> list[dict[str, Any]]:
        raw = self.app._settings.value("live/position_bookmarks", "[]")
        try:
            rows = json.loads(str(raw or "[]"))
        except (TypeError, ValueError):
            return []
        result = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not str(row.get("map") or "").strip():
                continue
            try:
                result.append({
                    "name": str(row.get("name") or "").strip(),
                    "map": str(row["map"]),
                    **{key: float(row.get(key, 0.0) or 0.0)
                       for key in ("x", "y", "z", "pitch", "yaw", "roll")},
                })
            except (TypeError, ValueError):
                continue
        return result[:100]

    def _store_bookmarks(self) -> None:
        self.app._settings.setValue(
            "live/position_bookmarks",
            json.dumps(self._bookmarks, ensure_ascii=False, separators=(",", ":")))

    @pyqtProperty(list, notify=runtimeStateChanged)
    def bookmarkModel(self) -> list[dict[str, Any]]:
        labels = self.strings.get("labels", {})
        result = []
        for index, bookmark in enumerate(self._bookmarks, 1):
            name = bookmark.get("name") or labels.get("bookmark_default", "Bookmark {number}").format(number=index)
            result.append({
                "label": labels.get("bookmark_item", "{name} · {map}").format(name=name, map=bookmark["map"]),
                "index": index - 1,
            })
        return result

    @pyqtProperty(str, notify=runtimeStateChanged)
    def positionText(self) -> str:
        labels = self.strings.get("labels", {})
        position = self._live_state.get("position") or self._live_state.get("position_state") or {}
        if not self._position_available(position):
            return labels.get("position_unavailable", "Position unavailable.")
        return labels.get("position_value", "{map} · X {x:.1f} · Y {y:.1f} · Z {z:.1f}").format(
            map=position.get("map", ""),
            x=float(position.get("x", 0.0) or 0.0),
            y=float(position.get("y", 0.0) or 0.0),
            z=float(position.get("z", 0.0) or 0.0))

    @staticmethod
    def _position_available(position: dict) -> bool:
        return bool(position.get("available", True)) and bool(str(position.get("map") or "").strip())

    @pyqtSlot(str)
    def saveBookmark(self, name: str) -> None:
        labels = self.strings.get("labels", {})
        position = self._live_state.get("position") or self._live_state.get("position_state") or {}
        if not self._position_available(position):
            self.set_runtime_result(labels.get("position_unavailable", "Position unavailable."), False)
            return
        name = name.strip() or labels.get("bookmark_default", "Bookmark {number}").format(
            number=len(self._bookmarks) + 1)
        self._bookmarks.append({
            "name": name, "map": str(position["map"]),
            **{key: float(position.get(key, 0.0) or 0.0)
               for key in ("x", "y", "z", "pitch", "yaw", "roll")},
        })
        self._store_bookmarks()
        self.runtimeStateChanged.emit()

    @pyqtSlot(int)
    def teleportBookmark(self, index: int) -> None:
        labels = self.strings.get("labels", {})
        if not 0 <= index < len(self._bookmarks):
            return
        bookmark = self._bookmarks[index]
        position = self._live_state.get("position") or self._live_state.get("position_state") or {}
        current_map = str(position.get("map") or "").strip()
        if not current_map or str(bookmark.get("map") or "").strip().casefold() != current_map.casefold():
            self.set_runtime_result(labels.get("position_map_mismatch", "Bookmark is on another map."), False)
            return
        self.app.runtime_action("teleport_position", dict(bookmark))

    @pyqtSlot(int)
    def deleteBookmark(self, index: int) -> None:
        if 0 <= index < len(self._bookmarks):
            del self._bookmarks[index]
            self._store_bookmarks()
            self.runtimeStateChanged.emit()

    # -- live 失物 ---------------------------------------------------------
    @pyqtProperty(str, notify=runtimeStateChanged)
    def lostLootText(self) -> str:
        labels = self.strings.get("labels", {})
        state = self._live_state.get("lost_loot") or self._live_state.get("lost_loot_state") or {}
        if not state.get("available"):
            return labels.get("lost_loot_unavailable", "Lost Loot is unavailable.")
        return labels.get("lost_loot_value", "{count} item(s) · {free_slots} free backpack slot(s)").format(
            count=int(state.get("count", 0) or 0), free_slots=int(state.get("free_slots", 0) or 0))

    @pyqtProperty(bool, notify=runtimeStateChanged)
    def canClaimLostLoot(self) -> bool:
        # The player may have travelled since the last snapshot. Let the backend
        # refresh machine/count/capacity during its existing claim preflight;
        # never permanently disable this action using a stale availability bit.
        return self.liveMode and not self._runtime_busy and not self._inventory_mutation_blocked

    # -- AppBridge 推入状态 -------------------------------------------------
    def apply_runtime_state(self, state: dict) -> None:
        if isinstance(state, dict):
            self._live_state.update(state)
            self.runtimeStateChanged.emit()

    def set_runtime_result(self, message: str, ok: bool = True) -> None:
        self._runtime_status = str(message or "")
        self._runtime_status_ok = bool(ok)
        self.runtimeStateChanged.emit()

    def set_runtime_busy(self, busy: bool) -> None:
        self._runtime_busy = bool(busy)
        self.runtimeStateChanged.emit()

    def set_inventory_mutation_blocked(self, blocked: bool) -> None:
        self._inventory_mutation_blocked = bool(blocked)
        self.runtimeStateChanged.emit()
