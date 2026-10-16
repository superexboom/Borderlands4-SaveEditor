// 全局统一的选择框：HusSelect 默认 clearEnabled:true，悬停时指示箭头会变成
// 清除按钮（点击清空 currentIndex 而不展开弹层），对绑定 VM 状态的选择框是
// 误触陷阱（表现类似"下拉失效"）。本项目选择框均有 VM 绑定与显式 None/Random
// 选项，统一关闭清除；个别需要清除的场景显式 clearEnabled: true 覆盖即可。
//
// implicitWidth 固定为与文本无关的常量：HusSelect 原实现 implicitWidth 随当前
// 显示文本变化，放在 GridLayout/RowLayout 里选中长文本时列宽会突然跳动（抽搐）。
// 需要更宽的场合由使用方显式 Layout.preferredWidth/fillWidth 指定。
import QtQuick
import QtQuick.Controls
import HuskarUI.Basic

HusSelect {
    id: select
    clearEnabled: false
    implicitWidth: 160
    showToolTip: true
    // Tooltip text of one model row. Empty when it would only repeat the row's own
    // label (the "None" entries carry their label as tooltip).
    function rowTip(row) {
        if (!row || typeof row !== "object") return "";
        var text = String(row.tooltip || row.hint || row.detail || "").trim();
        var label = String(row[select.textRole] || "").trim();
        var plain = row.marker ? label.replace(String(row.marker), "").trim() : label;
        return text === label || text === plain ? "" : text;
    }
    // The row the closed box shows. Pages that drive displayText from the VM leave
    // currentIndex stale, so match the shown text first.
    function shownRow() {
        var rows = select.model;
        if (!rows || rows.length === undefined) return null;
        var shown = String(select.displayText || "");
        for (var i = 0; i < rows.length; i++) {
            if (rows[i] && typeof rows[i] === "object" && String(rows[i][select.textRole] || "") === shown)
                return rows[i];
        }
        return select.currentIndex >= 0 ? rows[select.currentIndex] : null;
    }
    toolTipDelegate: Item {
        id: entryTip
        readonly property string tipText: select.model && index >= 0 ? select.rowTip(select.model[index]) : ""
        property bool rowHovered: hovered
        // HusSelect patch: pointer position in this item's coordinates, so the tip
        // opens next to the mouse instead of under the middle of the row
        property point rowPoint: hoverPosition
        onRowHoveredChanged: {
            if (rowHovered) HoverTip.showFor(entryTip, tipText, rowPoint.x, rowPoint.y);
            else HoverTip.hideFor(entryTip);
        }
        onRowPointChanged: if (rowHovered) HoverTip.showFor(entryTip, tipText, rowPoint.x, rowPoint.y)
        Component.onDestruction: HoverTip.hideFor(entryTip)
    }
    HoverHandler {
        id: controlHover
        onHoveredChanged: {
            if (!hovered || select.popup.visible) HoverTip.hideFor(select);
            else HoverTip.showFor(select, select.rowTip(select.shownRow()), point.position.x, point.position.y);
        }
    }
    // A click inside the hover delay used to open the box's tip on top of the list
    Connections {
        target: select.popup
        function onAboutToShow() { HoverTip.hideFor(select); }
    }
}
