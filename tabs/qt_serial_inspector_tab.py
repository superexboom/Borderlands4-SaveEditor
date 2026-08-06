"""Read-only serial inspector.

Paste one Base85 code or one decoded string and see everything the project knows
about that item: header fields, resolved name/rarity, the rendered item card, a
per-part breakdown with parsed augment ids, the raw bit layout, generation rule
violations and a round-trip check.

This tab never writes to the save. All analysis comes from ``core.serial_inspect``
and the card image from ``core.card_image``, so it always agrees with what the
item list and the editors show.
"""

from __future__ import annotations

import json
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core import card_image, resource_loader, serial_inspect

UI_LOC_KEY = "serial_inspector_tab"

_FALLBACK_LOC: dict[str, Any] = {
    "labels": {
        "input": "Serial (Base85 or decoded)",
        "summary": "Summary",
        "card": "Item card",
        "parts": "Parts",
        "bits": "Bit layout",
        "raw": "Raw data",
        "rules": "Generation rules",
        "empty": "Paste a serial above to inspect it.",
        "no_card": "No card available for this item type.",
        "item_id": "Item ID",
        "manufacturer": "Manufacturer",
        "type": "Type",
        "level": "Level",
        "seed": "Seed",
        "name": "Name",
        "rarity": "Rarity",
        "name_source": "Name source",
        "base85": "Base85",
        "decoded": "Decoded",
        "components": "Components",
        "roundtrip": "Round-trip",
        "bit_total": "Total bits",
        "bit_header": "Header bits",
        "bit_padding": "Padding bits",
        "part_total": "Parts",
        "implicit_level_one": "Implicit level 1",
    },
    "buttons": {
        "inspect": "Inspect",
        "paste": "Paste",
        "clear": "Clear",
        "copy_json": "Copy JSON",
        "export_json": "Export JSON",
        "save_card": "Save card image",
    },
    "parts_columns": ["#", "Ref", "Category", "Rarity", "Name", "Effect", "Description"],
    "bits_columns": ["#", "Token", "Bits", "Length", "Byte", "Value"],
    "effect_state": {
        "described": "described",
        "cosmetic": "cosmetic",
        "unmapped": "unmapped payload",
        "unknown": "unknown ref",
    },
    "status": {
        "legal": "Legal",
        "incomplete": "Incomplete",
        "modified": "Modified",
        "conditional": "Conditional",
        "unknown": "Unknown",
    },
    "roundtrip": {
        "match": "re-encodes identically",
        "differs": "re-encodes to a different code",
        "failed": "re-encode failed",
    },
    "rules_labels": {
        "not_weapon": "Generation rules apply to firearms only; this item type has no rule tree.",
        "no_data": "No generation rule data is available for this weapon.",
        "composition": "Composition",
        "parent": "Parent",
        "availability": "Availability",
        "coverage": "Rule coverage complete",
        "base_tags": "Base tags",
        "tag_limits": "Tag limits",
        "groups": "Part groups",
        "violations": "Issues",
        "yes": "yes",
        "no": "no",
    },
    "rules_columns": ["Group", "Selected", "Legal", "Pool", "State"],
    "rules_state": {
        "ok": "ok",
        "incomplete": "not filled",
        "unreachable": "unreachable",
    },
}

# Violation codes carry no text of their own. weapon_rules already localizes each
# one for all four languages (see tabs.qt_weapon_generator_tab._rule_violation_text),
# so reuse those keys rather than duplicating 17 strings per language here.
_VIOLATION_FALLBACK = {
    "invalid_serial": "Serial could not be parsed",
    "tag_count_below": "Tagged parts are missing",
}


def _tr(loc: dict[str, Any], section: str, key: str) -> str:
    """Localized string with a hard fallback, so a missing key never crashes the tab."""
    value = (loc.get(section) or {}).get(key)
    if isinstance(value, str) and value:
        return value
    return str((_FALLBACK_LOC.get(section) or {}).get(key) or key)


def _columns(loc: dict[str, Any], key: str) -> list[str]:
    value = loc.get(key)
    if isinstance(value, list) and value:
        return [str(entry) for entry in value]
    return list(_FALLBACK_LOC[key])


class QtSerialInspectorTab(QWidget):
    """Read-only inspector for a single item serial."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.current_lang = "zh-CN"
        self._load_localization()
        self._report: dict[str, Any] = {}
        self._card_pixmap = None

        self.ui_labels: dict[str, QLabel] = {}
        self.ui_buttons: dict[str, QPushButton] = {}
        self.ui_groups: dict[str, QGroupBox] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        root.addWidget(self._build_input_group())

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1000, int(card_image.CARD_MAX_WIDTH) + 60])
        root.addWidget(splitter, 1)

        self._set_placeholder()

    # ------------------------------------------------------------------ build

    def _build_input_group(self) -> QGroupBox:
        group = QGroupBox(_tr(self.loc, "labels", "input"))
        self.ui_groups["input"] = group
        layout = QVBoxLayout(group)

        self.input_edit = QPlainTextEdit()
        self.input_edit.setObjectName("inspectorInput")
        self.input_edit.setMaximumHeight(70)
        self.input_edit.setPlaceholderText(_tr(self.loc, "labels", "empty"))
        layout.addWidget(self.input_edit)

        row = QHBoxLayout()
        for key, slot in (
            ("inspect", self.inspect),
            ("paste", self._paste),
            ("clear", self.clear),
            ("copy_json", self._copy_json),
            ("export_json", self._export_json),
            ("save_card", self._save_card),
        ):
            button = QPushButton(_tr(self.loc, "buttons", key))
            button.clicked.connect(slot)
            self.ui_buttons[key] = button
            row.addWidget(button)
        row.addStretch(1)

        self.status_badge = QLabel()
        self.status_badge.setObjectName("genBuildStatus")
        self.status_badge.setVisible(False)
        row.addWidget(self.status_badge)
        layout.addLayout(row)
        return group

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("inspectorSummary")
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary_label.setWordWrap(True)
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        summary_group = QGroupBox(_tr(self.loc, "labels", "summary"))
        self.ui_groups["summary"] = summary_group
        # The summary is a 12-row table; without a scroll area it either clips or
        # steals all the vertical space from the parts table.
        summary_scroll = QScrollArea()
        summary_scroll.setWidgetResizable(True)
        summary_scroll.setFrameShape(QFrame.Shape.NoFrame)
        summary_scroll.setWidget(self.summary_label)
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.addWidget(summary_scroll)
        summary_group.setMinimumHeight(320)
        summary_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(summary_group)

        self.detail_tabs = QTabWidget()
        self.parts_table = self._make_table(_columns(self.loc, "parts_columns"))
        self.bits_table = self._make_table(_columns(self.loc, "bits_columns"))
        self.rules_view = QTextEdit()
        self.rules_view.setReadOnly(True)
        self.raw_view = QPlainTextEdit()
        self.raw_view.setReadOnly(True)
        self.raw_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.detail_tabs.addTab(self.parts_table, _tr(self.loc, "labels", "parts"))
        self.detail_tabs.addTab(self.bits_table, _tr(self.loc, "labels", "bits"))
        self.detail_tabs.addTab(self.rules_view, _tr(self.loc, "labels", "rules"))
        self.detail_tabs.addTab(self.raw_view, _tr(self.loc, "labels", "raw"))
        layout.addWidget(self.detail_tabs, 1)
        return panel

    def _build_right_panel(self) -> QWidget:
        group = QGroupBox(_tr(self.loc, "labels", "card"))
        self.ui_groups["card"] = group
        layout = QVBoxLayout(group)

        self.card_scroll = QScrollArea()
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Cards are authored against a 520px table; narrower than that and the
        # stat rows wrap into each other.
        self.card_scroll.setMinimumWidth(int(card_image.CARD_MAX_WIDTH) + 40)
        self.card_label = QLabel()
        self.card_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.card_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.card_scroll.setWidget(self.card_label)
        layout.addWidget(self.card_scroll, 1)
        return group

    @staticmethod
    def _make_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setObjectName("inspectorTable")
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        return table

    # ------------------------------------------------------------------ logic

    def inspect(self):
        text = self.input_edit.toPlainText().strip()
        if not text:
            self.clear()
            return
        self._report = serial_inspect.inspect_serial(text, self.current_lang)
        self._render(self._report)

    def clear(self):
        self._report = {}
        self._card_pixmap = None
        self.input_edit.clear()
        self.parts_table.setRowCount(0)
        self.bits_table.setRowCount(0)
        self.rules_view.clear()
        self.raw_view.clear()
        self.card_label.clear()
        self.status_badge.setVisible(False)
        self._set_placeholder()

    def _set_placeholder(self):
        self.summary_label.setText(_tr(self.loc, "labels", "empty"))

    def _paste(self):
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            self.input_edit.setPlainText(clipboard.text().strip())
            self.inspect()

    def _render(self, report: dict[str, Any]):
        self._render_summary(report)
        self._render_status(report)
        self._render_parts(report)
        self._render_bits(report)
        self._render_rules(report)
        self._render_raw(report)
        self._render_card(report)

    def _render_summary(self, report: dict[str, Any]):
        def row(key: str, value: Any) -> str:
            from html import escape

            return (
                "<tr><td style='padding:1px 10px 1px 0;opacity:0.75;'>%s</td>"
                "<td style='padding:1px 0;'>%s</td></tr>"
                % (escape(_tr(self.loc, "labels", key)), escape("" if value is None else str(value)))
            )

        if not report.get("ok"):
            self.summary_label.setText(str(report.get("error") or ""))
            return

        rt = report.get("roundtrip") or {}
        if not rt.get("ok"):
            rt_text = _tr(self.loc, "roundtrip", "failed")
        elif rt.get("matches_input"):
            rt_text = _tr(self.loc, "roundtrip", "match")
        else:
            rt_text = _tr(self.loc, "roundtrip", "differs")

        bits = report.get("bit_layout") or {}
        counts = report.get("part_counts") or {}
        rows = [
            row("name", report.get("display_name")),
            row("rarity", report.get("rarity")),
            row("item_id", report.get("item_id")),
            row("manufacturer", "%s / %s" % (report.get("manufacturer") or "", report.get("manufacturer_en") or "")),
            row("type", "%s / %s" % (report.get("type") or "", report.get("type_en") or "")),
            row("level", report.get("level")),
            row("seed", report.get("seed")),
            row("name_source", report.get("display_source")),
            row("part_total", counts.get("total")),
            row("bit_total", "%s (%s bytes)" % (bits.get("total_bits"), bits.get("total_bytes"))),
            row("bit_padding", bits.get("padding_bits")),
            row("roundtrip", rt_text),
        ]
        if report.get("implicit_level_one"):
            rows.append(row("implicit_level_one", _tr(self.loc, "rules_labels", "yes")))
        self.summary_label.setText("<table>%s</table>" % "".join(rows))

    def _render_status(self, report: dict[str, Any]):
        status = str(report.get("status") or "")
        if not report.get("ok") or not status:
            self.status_badge.setVisible(False)
            return
        self.status_badge.setText(_tr(self.loc, "status", status) or status)
        self.status_badge.setProperty("ruleStatus", status)
        # Qt does not restyle on a dynamic property change by itself.
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        self.status_badge.setVisible(True)

    def _render_parts(self, report: dict[str, Any]):
        rows = report.get("parts") or []
        table = self.parts_table
        table.setRowCount(len(rows))
        for index, part in enumerate(rows):
            state = part.get("effect_state") or ""
            if not part.get("known"):
                state = "unknown"
            values = [
                str(index + 1),
                str(part.get("key") or ""),
                str(part.get("category") or ""),
                str(part.get("rarity") or ""),
                str(part.get("name") or ""),
                _tr(self.loc, "effect_state", state),
                str(part.get("description") or ""),
            ]
            for column, value in enumerate(values):
                table.setItem(index, column, QTableWidgetItem(value))

    def _render_bits(self, report: dict[str, Any]):
        bits = (report.get("bit_layout") or {}).get("blocks") or []
        table = self.bits_table
        table.setRowCount(len(bits))
        for index, block in enumerate(bits):
            values = [
                str(block.get("index")),
                str(block.get("token") or ""),
                "%s-%s" % (block.get("bit_start"), block.get("bit_end")),
                str(block.get("bit_len")),
                str(block.get("byte_start")),
                str(block.get("text") or ""),
            ]
            for column, value in enumerate(values):
                table.setItem(index, column, QTableWidgetItem(value))

    def _render_rules(self, report: dict[str, Any]):
        from html import escape

        def label(key: str) -> str:
            return _tr(self.loc, "rules_labels", key)

        if not report.get("ok"):
            self.rules_view.setPlainText("")
            return

        generation = report.get("generation") or {}
        if not generation:
            # Only the five firearm types have a rule tree; equipment has none.
            self.rules_view.setHtml("<p style='opacity:0.75;'>%s</p>" % escape(label("not_weapon")))
            return

        yes, no = label("yes"), label("no")
        rows = [
            (label("composition"), generation.get("composition_ref") or "-"),
            (label("parent"), generation.get("parent") or "-"),
            (label("availability"), generation.get("availability") or "-"),
            (label("coverage"), yes if generation.get("coverage_complete") else no),
            (label("base_tags"), ", ".join(str(tag) for tag in generation.get("base_tags") or []) or "-"),
        ]
        tag_rules = generation.get("tag_rules") or []
        if tag_rules:
            rows.append((
                label("tag_limits"),
                "; ".join(
                    "%s \u2264 %s" % (", ".join(str(tag) for tag in rule.get("tags") or []), rule.get("max", 1))
                    for rule in tag_rules
                ),
            ))

        html = [
            "<table cellspacing='0' cellpadding='2'>",
            "".join(
                "<tr><td style='padding-right:12px;opacity:0.75;'>%s</td><td>%s</td></tr>"
                % (escape(str(name)), escape(str(value)))
                for name, value in rows
            ),
            "</table>",
        ]

        groups = generation.get("groups") or {}
        if groups:
            columns = _columns(self.loc, "rules_columns")
            html.append("<p style='margin:8px 0 2px 0;font-weight:bold;'>%s</p>" % escape(label("groups")))
            html.append("<table cellspacing='0' cellpadding='3'><tr>")
            html.extend(
                "<th align='left' style='opacity:0.75;padding-right:14px;'>%s</th>" % escape(name)
                for name in columns
            )
            html.append("</tr>")
            for name in self._ordered_groups(generation):
                data = groups.get(name) or {}
                selected = len(data.get("selected") or [])
                low = data.get("effective_min", data.get("min"))
                high = data.get("effective_max", data.get("max"))
                legal = str(low) if low == high else "%s-%s" % (low, high)
                if not data.get("selected_reachable", True):
                    state, colour = _tr(self.loc, "rules_state", "unreachable"), "#E57373"
                elif not data.get("selected_terminal", True):
                    state, colour = _tr(self.loc, "rules_state", "incomplete"), "#FFB74D"
                else:
                    state, colour = _tr(self.loc, "rules_state", "ok"), ""
                style = " style='color:%s;'" % colour if colour else ""
                html.append(
                    "<tr><td style='padding-right:14px;'>%s"
                    "<span style='opacity:0.45;'> %s</span></td>"
                    "<td align='right' style='padding-right:14px;'>%d</td>"
                    "<td align='right' style='padding-right:14px;'>%s</td>"
                    "<td align='right' style='padding-right:14px;opacity:0.6;'>%d</td><td%s>%s</td></tr>"
                    % (
                        escape(self._group_label(name)),
                        # Several groups share one display name (underbarrel_acc and
                        # underbarrel_acc_vis both read "Underbarrel Accessory"), so
                        # keep the raw key visible to tell the rows apart.
                        escape(str(name)),
                        selected,
                        escape(legal),
                        len(data.get("allowed") or []),
                        style,
                        escape(state),
                    )
                )
            html.append("</table>")

        violations = report.get("violations") or []
        html.append("<p style='margin:8px 0 2px 0;font-weight:bold;'>%s</p>" % escape(label("violations")))
        if violations:
            html.append("<ul style='margin:0;'>")
            html.extend("<li>%s</li>" % escape(self._violation_text(item)) for item in violations)
            html.append("</ul>")
        else:
            html.append(
                "<p style='margin:0;opacity:0.75;'>%s</p>"
                % escape(self.rule_loc.get("matches_rules") or "-")
            )

        for warning in report.get("warnings") or []:
            html.append("<p style='margin:2px 0;color:#E57373;'>%s</p>" % escape(str(warning)))
        self.rules_view.setHtml("".join(html))

    @staticmethod
    def _ordered_groups(generation: dict[str, Any]) -> list[str]:
        """Groups in the weapon's declared part_types order, extras appended."""
        groups = generation.get("groups") or {}
        ordered: list[str] = []
        for name in generation.get("part_types") or []:
            name = str(name).casefold()
            if name in groups and name not in ordered:
                ordered.append(name)
        ordered.extend(sorted(set(groups) - set(ordered)))
        return ordered

    def _group_label(self, group: str) -> str:
        """Localize a selection group through the weapon editor's taxonomy keys,
        so the inspector names groups exactly like the weapon editor does."""
        part_type = self._group_types().get(str(group).casefold())
        taxonomy_key = self._taxonomy_keys().get(part_type or "")
        text = self.taxonomy_loc.get(taxonomy_key or "")
        if text:
            return str(text)
        return part_type or str(group).replace("_", " ").title()

    @staticmethod
    def _group_types() -> dict[str, str]:
        # Imported lazily: the weapon editor pulls in pandas and the catalog picker.
        from tabs.qt_weapon_editor_tab import WeaponEditorTab

        return WeaponEditorTab.GENERATION_GROUP_TYPES

    @staticmethod
    def _taxonomy_keys() -> dict[str, str]:
        from tabs.qt_weapon_editor_tab import WeaponEditorTab

        return WeaponEditorTab.TAXONOMY_KEYS

    def _violation_text(self, violation: dict[str, Any]) -> str:
        code = str(violation.get("code") or "")
        text = (
            self.rule_loc.get("violation_" + code)
            or _VIOLATION_FALLBACK.get(code)
            or code
        )
        group = violation.get("group")
        if group:
            text += " \u00b7 %s (%s)" % (self._group_label(str(group)), group)
        actual = violation.get("actual")
        limit = violation.get("min", violation.get("max"))
        if actual is not None and limit is not None:
            text += " (%s/%s)" % (actual, limit)
        for key in ("parts", "tags"):
            values = violation.get(key)
            if values:
                text += " \u00b7 %s" % ", ".join(str(entry) for entry in values)
        part = violation.get("part")
        if part:
            text += " \u00b7 %s" % part
        return text

    def _render_raw(self, report: dict[str, Any]):
        blocks = [
            "%s: %s" % (_tr(self.loc, "labels", "base85"), report.get("base85") or ""),
            "%s: %s" % (_tr(self.loc, "labels", "decoded"), report.get("decoded_full") or ""),
            "%s: %s" % (_tr(self.loc, "labels", "components"), report.get("decoded_parts") or ""),
            "",
            json.dumps(self._json_payload(report), ensure_ascii=False, indent=2),
        ]
        self.raw_view.setPlainText("\n".join(blocks))

    def _render_card(self, report: dict[str, Any]):
        self._card_pixmap = None
        self.card_label.clear()
        if not report.get("ok"):
            self.card_label.setText(_tr(self.loc, "labels", "no_card"))
            return
        item = card_image.card_item_from_report(report)
        columns = self._card_labels()
        pixmap = card_image.card_pixmap(
            item,
            self.current_lang,
            2.0,
            columns.get("level", "Lv"),
            columns,
        )
        if pixmap.isNull():
            self.card_label.setText(_tr(self.loc, "labels", "no_card"))
            return
        self._card_pixmap = pixmap
        self.card_label.setPixmap(pixmap)
        self.card_label.setMinimumSize(pixmap.size() / pixmap.devicePixelRatio())

    def _card_labels(self) -> dict[str, str]:
        """Card builders expect the items_tab 'columns' block for stat labels."""
        try:
            data = resource_loader.load_json_resource(
                resource_loader.get_ui_localization_file(self.current_lang)
            )
            columns = ((data or {}).get("items_tab") or {}).get("columns") or {}
            if columns:
                return dict(columns)
        except (KeyError, TypeError, ValueError, OSError):
            pass
        return {"level": "Lv"}

    @staticmethod
    def _json_payload(report: dict[str, Any]) -> dict[str, Any]:
        # "generation" carries the full rule tree; keep it out of the inline view.
        return {key: value for key, value in report.items() if key not in {"generation", "display"}}

    def _copy_json(self):
        if not self._report:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(json.dumps(self._report, ensure_ascii=False, indent=2, default=str))

    def _export_json(self):
        if not self._report:
            return
        path, _filter = QFileDialog.getSaveFileName(self, _tr(self.loc, "buttons", "export_json"), "serial.json", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self._report, handle, ensure_ascii=False, indent=2, default=str)
        except OSError:
            pass

    def _save_card(self):
        if self._card_pixmap is None or self._card_pixmap.isNull():
            return
        path, _filter = QFileDialog.getSaveFileName(self, _tr(self.loc, "buttons", "save_card"), "card.png", "PNG (*.png)")
        if path:
            self._card_pixmap.save(path)

    # ---------------------------------------------------------------- i18n

    def _load_localization(self):
        self.loc = dict(_FALLBACK_LOC)
        # Violation names and part-group names are already translated for the
        # weapon tabs; reuse them so the rules pane needs no duplicate strings.
        self.rule_loc: dict[str, Any] = {}
        self.taxonomy_loc: dict[str, Any] = {}
        try:
            data = resource_loader.load_json_resource(
                resource_loader.get_ui_localization_file(self.current_lang)
            )
        except (OSError, ValueError):
            data = None
        rule_loc = (data or {}).get("weapon_rules")
        if isinstance(rule_loc, dict):
            self.rule_loc = rule_loc
        taxonomy = ((data or {}).get("weapon_editor_tab") or {}).get("taxonomy")
        if isinstance(taxonomy, dict):
            self.taxonomy_loc = taxonomy
        section = (data or {}).get(UI_LOC_KEY)
        if isinstance(section, dict):
            merged = dict(_FALLBACK_LOC)
            merged.update(section)
            for key, value in _FALLBACK_LOC.items():
                if isinstance(value, dict):
                    combined = dict(value)
                    if isinstance(section.get(key), dict):
                        combined.update(section[key])
                    merged[key] = combined
            self.loc = merged

    def update_language(self, lang):
        self.current_lang = lang
        self._load_localization()
        self.ui_groups["input"].setTitle(_tr(self.loc, "labels", "input"))
        self.ui_groups["summary"].setTitle(_tr(self.loc, "labels", "summary"))
        self.ui_groups["card"].setTitle(_tr(self.loc, "labels", "card"))
        self.input_edit.setPlaceholderText(_tr(self.loc, "labels", "empty"))
        for key, button in self.ui_buttons.items():
            button.setText(_tr(self.loc, "buttons", key))
        self.parts_table.setHorizontalHeaderLabels(_columns(self.loc, "parts_columns"))
        self.bits_table.setHorizontalHeaderLabels(_columns(self.loc, "bits_columns"))
        for index, key in enumerate(("parts", "bits", "rules", "raw")):
            self.detail_tabs.setTabText(index, _tr(self.loc, "labels", key))
        if self._report:
            # Re-run so names, part descriptions and the card switch language.
            self._report = serial_inspect.inspect_serial(
                self.input_edit.toPlainText().strip(), self.current_lang
            )
            self._render(self._report)
        else:
            self._set_placeholder()
