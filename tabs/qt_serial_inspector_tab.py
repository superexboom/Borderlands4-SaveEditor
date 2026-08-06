"""Read-only serial inspector.

Paste one Base85 code or one decoded string and see everything the project knows
about that item: header fields, both serial forms, the rendered item card, a
per-part breakdown and generation rule violations.

The part breakdown is laid out as one framed card per part, reusing the weapon
editor's ``PartFrame``/``PartTypeBadge``/``PartName``/``PartDescription`` object
names so the two tabs look like the same application. It replaces an earlier
plain table, which elided long effect text with no way to read the rest.

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
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core import card_image, resource_loader, serial_inspect

UI_LOC_KEY = "serial_inspector_tab"

# Cards are authored against a 520px table and card_image renders them at that
# width. Displaying them 1:1 made the preview dominate the tab, so the pixmap is
# scaled down to a thumbnail; the full-resolution pixmap is kept for "save card"
# and for the click-to-zoom viewer.
CARD_DISPLAY_WIDTH = 300

_FALLBACK_LOC: dict[str, Any] = {
    "labels": {
        "input": "Serial (Base85 or decoded)",
        "summary": "Summary",
        "card": "Item card",
        "parts": "Parts",
        "rules": "Generation rules",
        "empty": "Paste a serial above to inspect it.",
        "no_card": "No card available for this item type.",
        "no_parts": "No parts to show.",
        "zoom_hint": "Click the card to enlarge",
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
        "copy": "Copy",
        "use": "Edit this form",
    },
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
        "no_rules": "No generation rule data is available for this item type.",
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
    # Part categories outside the firearm taxonomy the weapon editor localizes.
    # Named from what each one demonstrably is, not from the raw key: e.g.
    # passive_points are class-mod passive skills (passive_green_3_2_tier_4) and
    # inv_comp is the identity/rarity component (comp_05_legendary_*).
    "categories": {
        "passive_points": "Passive Skill",
        "inv_comp": "Item Component",
        "class_mod_body": "Class Mod Body",
        "action_skill_mod": "Action Skill Mod",
        "stat_group1": "Stat Roll 1",
        "stat_group2": "Stat Roll 2",
        "stat_group3": "Stat Roll 3",
        "stat_augment": "Stat Augment",
        "primary_augment": "Primary Augment",
        "secondary_augment": "Secondary Augment",
        "core_augment": "Core Augment",
        "payload": "Payload",
        "payload_augment": "Payload Augment",
        "element": "Element",
        "augment_element_resist": "Elemental Resistance",
        "augment_element_immunity": "Elemental Immunity",
        "augment_element_splat": "Elemental Splat",
        "augment_element_nova": "Elemental Nova",
        "unique": "Unique Part",
        "barrel_licensed": "Licensed Barrel",
    },
}

# Violation codes carry no text of their own. weapon_rules already localizes each
# one for all four languages (see tabs.qt_weapon_generator_tab._rule_violation_text),
# so reuse those keys rather than duplicating 17 strings per language here.
_VIOLATION_FALLBACK = {
    "invalid_serial": "Serial could not be parsed",
    "tag_count_below": "Tagged parts are missing",
}

# The weapon editor colours the 22 firearm part types it can edit. Serials also
# carry class-mod skills, enhancement augments and stat groups, so those get
# their own hues here instead of all collapsing to the same grey.
_EXTRA_CATEGORY_COLORS = {
    "passive_points": "#7E9BE0",
    "inv_comp": "#B39DDB",
    "class_mod_body": "#9575CD",
    "action_skill_mod": "#7986CB",
    "stat_group1": "#F06292",
    "stat_group2": "#F06292",
    "stat_group3": "#F06292",
    "stat_augment": "#EC7CA8",
    "primary_augment": "#4FC3F7",
    "secondary_augment": "#4DD0E1",
    "core_augment": "#29B6F6",
    "payload": "#FFA726",
    "payload_augment": "#FFB74D",
    "element": "#EF9A9A",
    "body_ele": "#EF9A9A",
    "augment_element_resist": "#E57373",
    "augment_element_immunity": "#E57373",
    "augment_element_splat": "#FF8A65",
    "augment_element_nova": "#FF8A65",
    "tediore_acc": "#AED581",
    "magazine_ted_thrown": "#DCE775",
    "barrel_licensed": "#B0BEC5",
    "unique": "#FFD54F",
}
_DEFAULT_CATEGORY_COLOR = "#B0BEC5"

# Effect state drives a small badge; only the two "something is missing" states
# need to draw the eye.
_EFFECT_STATE_COLORS = {
    "unmapped": "#FFB74D",
    "unknown": "#E57373",
}

_RARITY_COLORS = {
    "common": "#c8c8c8",
    "unusual": "#4ade80",
    "uncommon": "#4ade80",
    "rare": "#38bdf8",
    "veryrare": "#a855f7",
    "epic": "#a855f7",
    "legendary": "#fb923c",
    "unique": "#fbbf24",
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


class _CardViewer(QDialog):
    """Full-resolution card, sized to fit the screen. Click or Esc to close."""

    def __init__(self, pixmap, title: str, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        shown = pixmap
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            ratio = pixmap.devicePixelRatio() or 1.0
            limit_h = int(available.height() * 0.9 * ratio)
            limit_w = int(available.width() * 0.9 * ratio)
            if pixmap.height() > limit_h or pixmap.width() > limit_w:
                shown = pixmap.scaled(
                    limit_w,
                    limit_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                shown.setDevicePixelRatio(ratio)
        label.setPixmap(shown)
        layout.addWidget(label)

    def mousePressEvent(self, event):
        self.accept()
        super().mousePressEvent(event)


class _ClickableLabel(QLabel):
    """QLabel that runs a callback on left click, for the card thumbnail."""

    def __init__(self, on_click, parent: QWidget = None):
        super().__init__(parent)
        self._on_click = on_click

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and callable(self._on_click):
            self._on_click()
        super().mousePressEvent(event)


class QtSerialInspectorTab(QWidget):
    """Read-only inspector for a single item serial."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.current_lang = "zh-CN"
        self._load_localization()
        self._report: dict[str, Any] = {}
        self._card_pixmap = None
        self._syncing_summary = False
        self._part_widgets: list[QWidget] = []

        self.ui_labels: dict[str, QLabel] = {}
        self.ui_buttons: dict[str, QPushButton] = {}
        self.ui_groups: dict[str, QGroupBox] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        root.addWidget(self._build_input_group())

        # The point of this tab is the per-part effect list, so it gets every
        # spare pixel of height. The summary is a full-width 2-row strip rather
        # than a 13-row column: inside the left column it was ~70px too narrow
        # and had to scroll. The card sits in a narrow right-hand column, since
        # above the list it cost ~300px of height that the list wants. The
        # splitter keeps the card user-resizable/collapsible.
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

        # Both serial forms sit directly under the input, so pasting either one
        # shows the other: Base85 in, decoded string out, and the reverse. Each
        # row is read-only but selectable, with a copy button; "edit this form"
        # moves that text back into the input box for further work.
        self.form_rows: dict[str, QLineEdit] = {}
        for key in ("base85", "decoded"):
            row = QHBoxLayout()
            caption = QLabel(_tr(self.loc, "labels", key))
            caption.setMinimumWidth(70)
            self.ui_labels[key] = caption
            field = QLineEdit()
            field.setReadOnly(True)
            field.setObjectName("inspectorSerialForm")
            field.setCursorPosition(0)
            self.form_rows[key] = field
            copy_button = QPushButton(_tr(self.loc, "buttons", "copy"))
            copy_button.clicked.connect(lambda _checked=False, k=key: self._copy_form(k))
            use_button = QPushButton(_tr(self.loc, "buttons", "use"))
            use_button.clicked.connect(lambda _checked=False, k=key: self._use_form(k))
            self.ui_buttons["copy_" + key] = copy_button
            self.ui_buttons["use_" + key] = use_button
            row.addWidget(caption)
            row.addWidget(field, 1)
            row.addWidget(copy_button)
            row.addWidget(use_button)
            layout.addLayout(row)

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
        self.card_label = _ClickableLabel(self._zoom_card)
        self.card_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.card_label.setFixedWidth(CARD_DISPLAY_WIDTH)
        layout.addWidget(self.card_label)

        self.zoom_hint = QLabel(_tr(self.loc, "labels", "zoom_hint"))
        self.zoom_hint.setObjectName("PartDescription")
        self.zoom_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.zoom_hint.setWordWrap(True)
        self.zoom_hint.setVisible(False)
        self.ui_labels["zoom_hint"] = self.zoom_hint
        layout.addWidget(self.zoom_hint)
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

        # Parts are framed cards in a scroll area rather than table rows, so a
        # long description wraps and stays readable instead of being elided.
        self.parts_container = QWidget()
        self.parts_layout = QVBoxLayout(self.parts_container)
        self.parts_layout.setContentsMargins(4, 4, 4, 4)
        self.parts_layout.setSpacing(6)
        self.parts_layout.addStretch(1)

        self.parts_scroll = QScrollArea()
        self.parts_scroll.setWidgetResizable(True)
        self.parts_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.parts_scroll.setWidget(self.parts_container)

        self.rules_view = QTextEdit()
        self.rules_view.setReadOnly(True)

        self.detail_tabs.addTab(self.parts_scroll, _tr(self.loc, "labels", "parts"))
        self.detail_tabs.addTab(self.rules_view, _tr(self.loc, "labels", "rules"))
        return self.detail_tabs

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
        self._clear_parts()
        self.rules_view.clear()
        for field in self.form_rows.values():
            field.clear()
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

    def _copy_form(self, key: str):
        text = self.form_rows[key].text()
        clipboard = QGuiApplication.clipboard()
        if text and clipboard:
            clipboard.setText(text)

    def _use_form(self, key: str):
        """Move one form into the input box, so either can be edited and re-run."""
        text = self.form_rows[key].text()
        if not text:
            return
        self.input_edit.setPlainText(text)
        self.inspect()

    def _render(self, report: dict[str, Any]):
        self._render_forms(report)
        self._render_summary(report)
        self._render_status(report)
        self._render_parts(report)
        self._render_rules(report)
        self._render_card(report)

    def _render_forms(self, report: dict[str, Any]):
        for key, value in (
            ("base85", report.get("base85")),
            ("decoded", report.get("decoded_full")),
        ):
            field = self.form_rows[key]
            field.setText(str(value or ""))
            # Long serials otherwise show their tail, which hides the item id.
            field.setCursorPosition(0)

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

    # ------------------------------------------------------------------ parts

    def _clear_parts(self):
        for widget in self._part_widgets:
            self.parts_layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._part_widgets = []

    def _render_parts(self, report: dict[str, Any]):
        self._clear_parts()
        rows = report.get("parts") or []
        if not rows:
            empty = QLabel(_tr(self.loc, "labels", "no_parts"))
            empty.setObjectName("PartDescription")
            self.parts_layout.insertWidget(0, empty)
            self._part_widgets.append(empty)
            return
        for index, part in enumerate(rows):
            frame = self._create_part_frame(index, part)
            # Keep the trailing stretch last so the cards stay top-aligned.
            self.parts_layout.insertWidget(self.parts_layout.count() - 1, frame)
            self._part_widgets.append(frame)

    def _create_part_frame(self, index: int, part: dict[str, Any]) -> QFrame:
        """One framed part card, styled like the weapon editor's part list."""
        frame = QFrame()
        frame.setObjectName("PartFrame")
        layout = QVBoxLayout(frame)
        layout.setSpacing(3)
        layout.setContentsMargins(6, 4, 6, 4)

        category = str(part.get("category") or "")
        state = str(part.get("effect_state") or "")
        if not part.get("known"):
            state = "unknown"
        colour = self._category_color(category)

        header = QHBoxLayout()
        header.setSpacing(6)

        ordinal = QLabel("  %d  " % (index + 1))
        ordinal.setObjectName("PartIdBadge")
        header.addWidget(ordinal)

        type_label = QLabel(self._category_label(category))
        type_label.setObjectName("PartTypeBadge")
        type_label.setProperty("partColor", colour)
        type_label.setStyleSheet("color: %s; border-color: %s;" % (colour, colour))
        type_label.setWordWrap(True)
        header.addWidget(type_label)

        name = str(part.get("name") or "")
        if name:
            name_label = QLabel(name)
            name_label.setObjectName("PartName")
            name_label.setWordWrap(True)
            header.addWidget(name_label, 1)
        else:
            header.addStretch(1)

        rarity = str(part.get("rarity") or "")
        if rarity:
            rarity_label = QLabel(self._taxonomy_text(rarity))
            rarity_label.setObjectName("PartTypeBadge")
            rarity_colour = _RARITY_COLORS.get(rarity.replace(" ", "").casefold(), "")
            if rarity_colour:
                rarity_label.setStyleSheet(
                    "color: %s; border-color: %s;" % (rarity_colour, rarity_colour)
                )
            header.addWidget(rarity_label)

        # "described" is the normal case on almost every row, so badging it just
        # adds noise; only flag the states that mean something is missing.
        if state in _EFFECT_STATE_COLORS:
            state_label = QLabel(_tr(self.loc, "effect_state", state))
            state_label.setObjectName("PartTypeBadge")
            colour = _EFFECT_STATE_COLORS[state]
            state_label.setStyleSheet("color: %s; border-color: %s;" % (colour, colour))
            header.addWidget(state_label)

        # The ref key is what every probe, report and CSV row is keyed by, so it
        # stays visible rather than living only in a tooltip.
        ref_label = QLabel("  %s  " % str(part.get("key") or ""))
        ref_label.setObjectName("PartIdBadge")
        header.addWidget(ref_label)
        layout.addLayout(header)

        description = str(part.get("description") or "")
        if description:
            description_label = QLabel(description)
            description_label.setObjectName("PartDescription")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)

        internal = str(part.get("part") or "")
        if internal:
            frame.setToolTip("%s\n%s" % (part.get("key") or "", internal))
        return frame

    def _category_color(self, category: str) -> str:
        key = category.casefold()
        part_type = self._group_types().get(key)
        colour = self._part_type_colors().get(part_type or "")
        if colour:
            return str(colour)
        return _EXTRA_CATEGORY_COLORS.get(key, _DEFAULT_CATEGORY_COLOR)

    def _taxonomy_text(self, term: str) -> str:
        """Localize an English taxonomy term (part type or rarity) like the
        weapon editor does, or return it unchanged when there is no entry."""
        key = self._taxonomy_keys().get(str(term))
        text = self.taxonomy_loc.get(key or "")
        return str(text) if text else str(term)

    def _category_label(self, category: str) -> str:
        """Localize a part category, falling back to the raw key."""
        if not category:
            return "-"
        key = category.casefold()
        # Categories outside the firearm taxonomy (class-mod skills, augments,
        # stat groups) have no weapon-editor entry, so they carry their own
        # localized names here rather than showing a raw key like "inv_comp".
        own = _tr(self.loc, "categories", key)
        if own != key:
            return own
        return self._group_label(category)

    # ------------------------------------------------------------------ rules

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

    @staticmethod
    def _part_type_colors() -> dict[str, str]:
        from tabs.qt_weapon_editor_tab import WeaponEditorTab

        return WeaponEditorTab.PART_TYPE_COLORS

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

    # ------------------------------------------------------------------- card

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
        # Keep the full-resolution pixmap for _save_card and the zoom viewer, and
        # show a thumbnail so the part list keeps the width without degrading the
        # exported image.
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
        self.card_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.card_label.setToolTip(_tr(self.loc, "labels", "zoom_hint"))
        self.zoom_hint.setVisible(True)

    def _clear_card(self, text: str = ""):
        """Reset the card slot, releasing the height the last card reserved."""
        self.card_label.clear()
        self.card_label.setFixedHeight(self.card_label.fontMetrics().height() + 4)
        self.card_label.setCursor(Qt.CursorShape.ArrowCursor)
        self.card_label.setToolTip("")
        if hasattr(self, "zoom_hint"):
            self.zoom_hint.setVisible(False)
        if text:
            self.card_label.setText(text)

    def _zoom_card(self):
        """Show the card at full resolution; the thumbnail is too small to read."""
        if self._card_pixmap is None or self._card_pixmap.isNull():
            return
        viewer = _CardViewer(self._card_pixmap, _tr(self.loc, "labels", "card"), self)
        viewer.exec()

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

    # ------------------------------------------------------------------ export

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
        for key in ("base85", "decoded"):
            self.ui_labels[key].setText(_tr(self.loc, "labels", key))
            self.ui_buttons["copy_" + key].setText(_tr(self.loc, "buttons", "copy"))
            self.ui_buttons["use_" + key].setText(_tr(self.loc, "buttons", "use"))
        self.zoom_hint.setText(_tr(self.loc, "labels", "zoom_hint"))
        for key in ("inspect", "paste", "clear", "copy_json", "export_json", "save_card"):
            self.ui_buttons[key].setText(_tr(self.loc, "buttons", key))
        for index, key in enumerate(("parts", "rules")):
            self.detail_tabs.setTabText(index, _tr(self.loc, "labels", key))
        if self._report:
            # Re-run so names, part descriptions and the card switch language.
            self._report = serial_inspect.inspect_serial(
                self.input_edit.toPlainText().strip(), self.current_lang
            )
            self._render(self._report)
        else:
            self._set_placeholder()
