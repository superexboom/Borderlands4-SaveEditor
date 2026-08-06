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

# Cards are authored against a 520px table and card_image renders them at that
# width. Displaying them 1:1 made the preview dominate the tab, so the pixmap is
# scaled down to a thumbnail; the full-resolution pixmap is kept for "save card".
CARD_DISPLAY_WIDTH = 300

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
        self._syncing_summary = False

        self.ui_labels: dict[str, QLabel] = {}
        self.ui_buttons: dict[str, QPushButton] = {}
        self.ui_groups: dict[str, QGroupBox] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        root.addWidget(self._build_input_group())

        # The point of this tab is the per-part effect table, so it gets every
        # spare pixel of height. The summary is a full-width 2-row strip rather
        # than a 13-row column: inside the left column it was ~70px too narrow
        # and had to scroll. The card moves into a narrow right-hand column,
        # since above the table it cost ~300px of height that the table wants,
        # and a horizontal splitter stretched the 2-row summary to the card's
        # height. The splitter keeps the card user-resizable/collapsible.
        root.addWidget(self._build_summary_group())

        body = QSplitter(Qt.Orientation.Horizontal, self)
        body.addWidget(self._build_detail_tabs())
        body.addWidget(self._build_card_column())
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 0)
        body.setSizes([1000, CARD_DISPLAY_WIDTH + 40])
        root.addWidget(body, 1)

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

    def _build_summary_group(self) -> QGroupBox:
        group = QGroupBox(_tr(self.loc, "labels", "summary"))
        self.ui_groups["summary"] = group
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 6, 8, 6)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("inspectorSummary")
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary_label.setWordWrap(False)
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        # Two horizontal rows of label/value pairs need to scroll sideways on a
        # narrow window rather than wrap into an unpredictable number of lines.
        self.summary_scroll = QScrollArea()
        self.summary_scroll.setWidgetResizable(True)
        self.summary_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.summary_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.summary_scroll.setWidget(self.summary_label)
        layout.addWidget(self.summary_scroll)
        group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        return group

    def _build_card_column(self) -> QScrollArea:
        group = QGroupBox(_tr(self.loc, "labels", "card"))
        self.ui_groups["card"] = group
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 6, 6, 6)

        # The label carries the size: QScrollArea reports a constant 6x15 sizeHint,
        # so wrapping the card in one under a Maximum policy collapsed it to ~50px
        # and grew a scrollbar over the card. Here the label is fixed to the
        # thumbnail size and the group hugs it.
        self.card_label = QLabel()
        self.card_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.card_label.setFixedWidth(CARD_DISPLAY_WIDTH)
        layout.addWidget(self.card_label)
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        # Pin the card to the top of its column, and let it scroll only when the
        # window is genuinely too short for the card.
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.addWidget(group)
        inner_layout.addStretch(1)

        column = QScrollArea()
        column.setWidgetResizable(True)
        column.setFrameShape(QFrame.Shape.NoFrame)
        column.setWidget(inner)
        return column

    def _build_detail_tabs(self) -> QTabWidget:
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
        return self.detail_tabs

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
        self._clear_card()
        self.status_badge.setVisible(False)
        self._set_placeholder()

    def _set_placeholder(self):
        self.summary_label.setText(_tr(self.loc, "labels", "empty"))
        self._sync_summary_height()

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
        from html import escape

        if not report.get("ok"):
            self.summary_label.setText(str(report.get("error") or ""))
            self._sync_summary_height()
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
        # Two rows: identity on top, encoding facts below. Laid out horizontally
        # so the summary costs ~2 lines of height instead of 13.
        first = [
            ("name", report.get("display_name")),
            ("rarity", report.get("rarity")),
            ("type", "%s / %s" % (report.get("type") or "", report.get("type_en") or "")),
            ("manufacturer", "%s / %s" % (report.get("manufacturer") or "", report.get("manufacturer_en") or "")),
            ("level", report.get("level")),
        ]
        second = [
            ("item_id", report.get("item_id")),
            ("seed", report.get("seed")),
            ("part_total", counts.get("total")),
            ("bit_total", "%s (%s bytes)" % (bits.get("total_bits"), bits.get("total_bytes"))),
            ("bit_padding", bits.get("padding_bits")),
            ("roundtrip", rt_text),
            ("name_source", report.get("display_source")),
        ]
        if report.get("implicit_level_one"):
            second.append(("implicit_level_one", _tr(self.loc, "rules_labels", "yes")))

        def cells(pairs: list[tuple[str, Any]]) -> str:
            out = []
            for key, value in pairs:
                out.append(
                    "<td style='padding:1px 6px 1px 0;opacity:0.7;white-space:nowrap;'>%s</td>"
                    "<td style='padding:1px 18px 1px 0;white-space:nowrap;'>%s</td>"
                    % (
                        escape(_tr(self.loc, "labels", key)),
                        escape("" if value is None else str(value)),
                    )
                )
            # Each row is its own table: sharing one grid would pad every column to
            # the widest of the two rows and blow the width past the viewport.
            return (
                "<table style='border-collapse:collapse;'><tr>%s</tr></table>"
                % "".join(out)
            )

        self.summary_label.setText(cells(first) + cells(second))
        self._sync_summary_height()

    def _sync_summary_height(self):
        """Reserve room for the horizontal scrollbar so row 2 is never clipped."""
        # setFixedHeight re-triggers layout, which can re-enter resizeEvent; guard
        # against that and against redundant no-op writes.
        if self._syncing_summary:
            return
        self._syncing_summary = True
        try:
            label = self.summary_label
            scroll = self.summary_scroll
            hint = label.sizeHint()
            height = hint.height()
            if hint.width() > scroll.viewport().width():
                height += scroll.horizontalScrollBar().sizeHint().height()
            height += 2
            if scroll.height() != height:
                scroll.setFixedHeight(height)
        finally:
            self._syncing_summary = False

    def resizeEvent(self, event):
        # Whether the horizontal scrollbar is needed depends on the width.
        super().resizeEvent(event)
        self._sync_summary_height()

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
                item = QTableWidgetItem(value)
                # Columns are sized to contents and Qt elides what will not fit,
                # so long effect text (worst in en-US, which is wordier than zh)
                # was unreadable with no way to see the rest. Carry the full text
                # in a tooltip; only where it can actually be clipped.
                if value:
                    item.setToolTip(value)
                table.setItem(index, column, item)

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
            # Rules cover every inventory root that ships generation data; this
            # branch is now only reached by roots the index has no rules for.
            self.rules_view.setHtml("<p style='opacity:0.75;'>%s</p>" % escape(label("no_rules")))
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
        self._clear_card(_tr(self.loc, "labels", "no_card") if not report.get("ok") else "")
        if not report.get("ok"):
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
            self._clear_card(_tr(self.loc, "labels", "no_card"))
            return
        self._card_pixmap = pixmap
        # Keep the full-resolution pixmap for _save_card and show a thumbnail, so
        # the table keeps the width without degrading the exported image.
        preview = pixmap
        logical_width = pixmap.width() / pixmap.devicePixelRatio()
        if logical_width > CARD_DISPLAY_WIDTH:
            preview = pixmap.scaledToWidth(
                int(CARD_DISPLAY_WIDTH * pixmap.devicePixelRatio()),
                Qt.TransformationMode.SmoothTransformation,
            )
            preview.setDevicePixelRatio(pixmap.devicePixelRatio())
        self.card_label.setPixmap(preview)
        # Width is already fixed; only the height follows the card.
        self.card_label.setFixedHeight(
            int(preview.height() / preview.devicePixelRatio())
        )

    def _clear_card(self, text: str = ""):
        """Reset the card slot, releasing the height the last card reserved."""
        self.card_label.clear()
        self.card_label.setFixedHeight(self.card_label.fontMetrics().height() + 4)
        if text:
            self.card_label.setText(text)

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
