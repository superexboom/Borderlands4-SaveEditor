import QtQuick
import QtQuick.Layouts
import HuskarUI.Basic

Flow {
    id: legend
    property bool chinese: appBridge.language === "zh-CN"
    spacing: 12
    Repeater {
        model: [
            { label: legend.chinese ? "合法候选" : "Natural", color: "#4a90e2" },
            { label: legend.chinese ? "条件未满足" : "Blocked", color: "#e6a439" },
            { label: legend.chinese ? "魔改配件" : "Modified", color: "#ce5b5b" },
            { label: legend.chinese ? "规则未知" : "Unknown", color: "#687080" }
        ]
        delegate: Row {
            spacing: 5
            Rectangle {
                width: 9; height: 9; radius: 2
                anchors.verticalCenter: parent.verticalCenter
                color: modelData.color
            }
            HusText {
                text: modelData.label
                font.pixelSize: 11
                color: HusTheme.Primary.colorTextSecondary
            }
        }
    }
}
