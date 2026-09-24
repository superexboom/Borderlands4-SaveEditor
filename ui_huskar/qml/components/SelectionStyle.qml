// 全局选中态配色：对齐主线 stylesheet.qss 的 ::item:selected
// （selection_bg = 强调色 #4a90e2、文字反白），深浅主题各自合适。
// HuskarUI 的 colorPrimaryBgHover 深色下是近白色（#ecf5fa），不能直接用作选中/悬停底色。
import QtQuick
import HuskarUI.Basic

QtObject {
    readonly property color bg: HusTheme.Primary.colorPrimary
    readonly property color text: "#FFFFFF"
    readonly property color secondaryText: "#E0FFFFFF"
    readonly property color tertiaryText: "#C0FFFFFF"
    // 次级选中底（对话框内的嵌套列表等需要弱一级的场合）
    readonly property color bgSubtle: HusTheme.isDark ? "#594a90e2" : "#404a90e2"

    // 悬停底色：对齐主线 theme_manager 的 button_hover（深 #4a4a58 / 浅 #d0d0d8）。
    // 不再使用 HuskarUI colorPrimaryBgHover（深色近白 #ecf5fa，悬停一片惨白）。
    readonly property color hover: HusTheme.isDark ? "#4a4a58" : "#d0d0d8"
    readonly property color hoverText: HusTheme.Primary.colorTextBase

    // legit 候选上色（对齐主线 set_candidate_states 的背景色 + 加粗）：
    // legal = 蓝底加粗、warning = 橙底，半透明叠加在玻璃面板上两侧主题都可读。
    readonly property color legitBg: HusTheme.isDark ? "#354a90e2" : "#304a90e2"
    readonly property color warningBg: HusTheme.isDark ? "#33e6a439" : "#2ae6a439"
    readonly property color invalidBg: HusTheme.isDark ? "#36ce5b5b" : "#24ce5b5b"
    readonly property color unknownBg: HusTheme.isDark ? "#28687080" : "#1f687080"

    // 目录卡片（主线 #catalogCard：bg_panel + 1px border_color + 10px 圆角）
    readonly property color cardBg: HusTheme.isDark ? "#4D23232A" : "#4DFCFCFF"
    readonly property color cardBorder: HusTheme.isDark ? "#9950505F" : "#80B4B4C8"
}
