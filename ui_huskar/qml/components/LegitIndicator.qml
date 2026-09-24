import QtQuick
import QtQuick.Layouts
import HuskarUI.Basic

// Compact whole-item legitimacy indicator. Full reasons stay in the shared
// rich-text popup so the configuration row remains stable at narrow widths.
Rectangle {
    id: indicator
    property string status: "unknown"
    property string label: "Unknown"
    property string detail: ""
    property bool compact: false
    signal clicked()

    implicitWidth: indicatorText.implicitWidth + 24
    implicitHeight: compact ? 26 : 30
    radius: 6
    color: status === "legal" ? (HusTheme.isDark ? "#294a90e2" : "#214a90e2")
         : status === "invalid" ? (HusTheme.isDark ? "#3dce5b5b" : "#24ce5b5b")
         : status === "incomplete" ? (HusTheme.isDark ? "#3de6a439" : "#24e6a439")
         : status === "conditional" ? (HusTheme.isDark ? "#3d9b7bd5" : "#249b7bd5")
         : (HusTheme.isDark ? "#3d687080" : "#24687080")
    border.width: 1
    border.color: status === "legal" ? "#4a90e2"
                : status === "invalid" ? "#ce5b5b"
                : status === "incomplete" ? "#e6a439"
                : status === "conditional" ? "#9b7bd5"
                : "#687080"

    HusText {
        id: indicatorText
        anchors.centerIn: parent
        text: indicator.label
        color: HusTheme.Primary.colorTextBase
        font.bold: true
        font.pixelSize: indicator.compact ? 11 : 12
    }
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        onClicked: indicator.clicked()
        onEntered: if (indicator.detail) HoverTip.showFor(indicator, indicator.detail, mouseX, mouseY)
        onPositionChanged: if (containsMouse && indicator.detail) HoverTip.showFor(indicator, indicator.detail, mouseX, mouseY)
        onExited: HoverTip.hideFor(indicator)
    }
}
