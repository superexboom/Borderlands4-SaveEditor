"""Render an item hover card to a QPixmap.

The item list shows its cards through ``QToolTip.showText``, which only accepts
rich text. The inspector needs the same visual as an embeddable widget, so this
module reuses the exact card HTML builders from ``tabs.qt_items_tab`` and paints
them with ``QTextDocument.drawContents``. Nothing here re-implements card layout;
if the cards change, the rendered image follows automatically.

Rendering is cheap (~40 ms at 1x, ~16 ms at 2x for a 540x503 card), so callers
render inline rather than on a worker thread.
"""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap, QTextDocument

__all__ = ["card_html", "card_pixmap", "CARD_MAX_WIDTH"]

# Matches the width the tooltip cards are authored against; wider documents just
# leave dead space, narrower ones wrap the stat rows badly.
CARD_MAX_WIDTH = 560.0

# The card HTML never sets a body text colour: in the item list the cards are
# shown through QToolTip, which paints them with the stylesheet's
# "QToolTip { color: #eef5f6 }". A QTextDocument has no stylesheet, so that text
# fell back to the default black and was unreadable on the dark card. Apply the
# same colour here so the rendered image matches the tooltip.
CARD_TEXT_COLOR = "#eef5f6"


def _card_builders() -> list[Callable[..., str]]:
    # Imported lazily: tabs.qt_items_tab pulls in widget classes, and core
    # modules must stay importable from headless scripts.
    from tabs.qt_items_tab import (
        classmod_card_html,
        enhancement_card_html,
        equipment_card_html,
        weapon_card_html,
    )

    return [weapon_card_html, equipment_card_html, classmod_card_html, enhancement_card_html]


def card_html(
    item: dict[str, Any],
    lang: str = "zh-CN",
    level_label: str = "Lv",
    stat_labels: dict[str, str] | None = None,
    character_level: int | None = None,
) -> str:
    """First card builder that recognises this item wins, mirroring the item list.

    Each builder returns an empty string for item types it does not handle, so
    the chain order here must stay the same as ``qt_items_tab`` line 1273.
    """
    for builder in _card_builders():
        try:
            if builder.__name__ == "classmod_card_html":
                html = builder(item, lang, level_label, stat_labels, character_level, 4)
            else:
                html = builder(item, lang, level_label, stat_labels)
        except Exception:
            continue
        if html:
            return html
    return ""


def card_pixmap(
    item: dict[str, Any],
    lang: str = "zh-CN",
    scale: float = 2.0,
    level_label: str = "Lv",
    stat_labels: dict[str, str] | None = None,
    character_level: int | None = None,
    max_width: float = CARD_MAX_WIDTH,
) -> QPixmap:
    """Render the item's card. Returns a null QPixmap when the item has no card."""
    html = card_html(item, lang, level_label, stat_labels, character_level)
    if not html:
        return QPixmap()
    return html_to_pixmap(html, scale=scale, max_width=max_width)


def html_to_pixmap(html: str, scale: float = 2.0, max_width: float = CARD_MAX_WIDTH) -> QPixmap:
    """Paint rich text onto a transparent, optionally supersampled pixmap."""
    if not html:
        return QPixmap()
    scale = max(1.0, float(scale or 1.0))

    document = QTextDocument()
    document.setDocumentMargin(0)
    # Set as the document default so any span with its own colour still wins.
    document.setDefaultStyleSheet("body,table,td,span,i,b { color: %s; }" % CARD_TEXT_COLOR)
    document.setHtml("<body>%s</body>" % html)
    document.setTextWidth(max_width)
    size = document.size()
    width = max(1, int(size.width() * scale + 0.5))
    height = max(1, int(size.height() * scale + 0.5))

    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))

    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.scale(scale, scale)
        document.drawContents(painter, QRectF(0, 0, size.width(), size.height()))
    finally:
        painter.end()

    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def card_item_from_report(report: dict[str, Any]) -> dict[str, Any]:
    """Adapt a ``serial_inspect.inspect_serial`` report to the card builders' input.

    The builders read the same keys as ``ProcessedItem``; the inspector has no
    save context, so container/slot are left blank.
    """
    return {
        "name": report.get("display_name") or "",
        "type": report.get("type") or "",
        "type_en": report.get("type_en") or "",
        "container": "",
        "slot": "",
        "manufacturer": report.get("manufacturer") or "",
        "manufacturer_en": report.get("manufacturer_en") or "",
        "id": report.get("item_id"),
        "level": report.get("level"),
        "serial": report.get("base85") or "",
        "decoded_full": report.get("decoded_full") or "",
        "decoded_parts": report.get("decoded_parts") or "",
        "rarity": report.get("rarity") or "",
        "weapon_stats": report.get("weapon_stats") or {},
        "equipment_stats": report.get("equipment_stats") or {},
    }
