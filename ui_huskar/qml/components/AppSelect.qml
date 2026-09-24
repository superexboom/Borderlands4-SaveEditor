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
    toolTipDelegate: Item {
        id: entryTip
        readonly property string tipText: {
            var row = select.model && index >= 0 ? select.model[index] : null;
            // Do not repeat a short field's selected label in a huge tooltip.
            return row ? String(row.tooltip || row.hint || row.detail || "") : "";
        }
        property bool rowHovered: hovered
        onRowHoveredChanged: {
            if (rowHovered) HoverTip.showFor(entryTip, tipText, 12, 0);
            else HoverTip.hideFor(entryTip);
        }
        Component.onDestruction: HoverTip.hideFor(entryTip)
    }
    HoverHandler {
        id: controlHover
        onHoveredChanged: {
            if (!hovered || select.popup.visible) HoverTip.hideFor(select);
            else {
                var row = select.model && select.currentIndex >= 0 ? select.model[select.currentIndex] : null;
                HoverTip.showFor(select, row ? row.tooltip || row.hint || row.detail || "" : "", point.position.x, point.position.y);
            }
        }
    }
}
