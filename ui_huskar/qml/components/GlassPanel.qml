// 半透明磨砂玻璃面板：对齐主线 stylesheet.qss 的 bg_primary / border_color
import QtQuick
import HuskarUI.Basic

Rectangle {
    radius: HusTheme.Primary.radiusPrimary
    color: HusTheme.isDark ? "#8C1E1E23" : "#8CFFFFFF"
    border.color: HusTheme.isDark ? "#66505060" : "#59B4B4C8"
    border.width: 1
    clip: true
}
