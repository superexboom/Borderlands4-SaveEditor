// 元素/属性选择芯片：对齐主线 #elemChip 样式（圆角胶囊、悬停描边、选中强调底）。
// legit 提示以上色呈现（合法=蓝底、警告=橙底，对齐主线 set_candidate_states），
// 不再向文本拼 ✓/! 标记。
import QtQuick
import HuskarUI.Basic

Rectangle {
    id: chip

    property string text: ""
    property string fullText: text      // 完整文本（悬停提示用）
    property bool checked: false
    property string kind: ""            // "" | "legal" | "warning" | "modified" | "unknown"
    signal clicked()

    SelectionStyle { id: chipStyle }

    implicitWidth: Math.min(chipText.implicitWidth + 24, 220)
    implicitHeight: 28
    radius: 14
    color: chip.kind === "legal" ? (chip.checked ? "#804a90e2" : (HusTheme.isDark ? "#354a90e2" : "#304a90e2"))
         : chip.kind === "warning" ? (HusTheme.isDark ? "#33e6a439" : "#2ae6a439")
         : chip.kind === "modified" ? (HusTheme.isDark ? "#36ce5b5b" : "#24ce5b5b")
         : chip.kind === "unknown" ? (HusTheme.isDark ? "#28687080" : "#1f687080")
         : chip.checked ? "#4a90e2"
         : HusTheme.isDark ? "#14FFFFFF" : "#0A000000"
    // legit 指示改为胶囊边框加粗着色（底色过暗看不清）：合法=蓝、警告=橙
    border.color: chip.kind === "legal" ? "#4a90e2"
                : chip.kind === "warning" ? "#e6a439"
                : chip.kind === "modified" ? "#ce5b5b"
                : chip.kind === "unknown" ? "#687080"
                : chip.checked ? "#4a90e2"
                : chipHover.containsMouse ? "#4a90e2"
                : chipStyle.cardBorder
    border.width: chip.checked || chip.kind !== "" ? 2 : 1

    HusText {
        id: chipText
        anchors.centerIn: parent
        width: parent.width - 20
        text: chip.text
        font.bold: true
        color: chip.checked ? "#FFFFFF"
             : chip.kind === "legal" ? (HusTheme.isDark ? "#9cc3f0" : "#2f6fc0")
             : chip.kind === "warning" ? (HusTheme.isDark ? "#f0c069" : "#9a6b12")
             : chip.kind === "modified" ? (HusTheme.isDark ? "#f19a9a" : "#a52e2e")
             : HusTheme.Primary.colorTextBase
        elide: Text.ElideRight
        horizontalAlignment: Text.AlignHCenter
    }

    MouseArea {
        id: chipHover
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: chip.clicked()
        onEntered: if (chip.fullText !== chip.text) HoverTip.showFor(chip, chip.fullText, mouseX, mouseY)
        onPositionChanged: if (containsMouse && chip.fullText !== chip.text) HoverTip.showFor(chip, chip.fullText, mouseX, mouseY)
        onExited: HoverTip.hideFor(chip)
    }
}
