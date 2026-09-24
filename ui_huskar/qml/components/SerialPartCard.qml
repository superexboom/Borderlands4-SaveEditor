// 序列号检视器：单配件卡片（对齐主线 PartFrame 结构）
// 用法：Column { Repeater { model: vmSerialInspector.parts; SerialPartCard { width: ...; part: modelData } } }
import QtQuick
import QtQuick.Layouts
import HuskarUI.Basic
import "PartColors.js" as PartColors

GlassPanel {
    id: card
    property var part: ({})
    // 选中态（Ctrl+C 复制由页面统一处理）
    property bool selected: false
    signal clicked()

    implicitHeight: contentColumn.implicitHeight + 16
    border.color: card.selected ? "#4a90e2" : (HusTheme.isDark ? "#66505060" : "#59B4B4C8")
    border.width: card.selected ? 2 : 1

    // 卡片选择（置于内容下层）
    MouseArea {
        anchors.fill: parent
        z: -1
        onClicked: card.clicked()
    }

    ColumnLayout {
        id: contentColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 8
        spacing: 4

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            HusTag {
                text: String(card.part.ordinal !== undefined ? card.part.ordinal : "")
                presetColor: "#4a90e2"
            }
            HusTag {
                text: card.part.category || ""
                presetColor: PartColors.visible(card.part.categoryColor || "#B0BEC5", HusTheme.isDark)
            }
            HusText {
                text: card.part.name || ""
                color: HusTheme.Primary.colorTextBase
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            HusTag {
                visible: !!card.part.rarity
                text: card.part.rarity || ""
                presetColor: PartColors.visible(card.part.rarityColor || "#B0BEC5", HusTheme.isDark)
            }
            HusTag {
                visible: !!card.part.state
                text: card.part.state || ""
                presetColor: PartColors.visible(card.part.stateColor || "#B0BEC5", HusTheme.isDark)
            }
            HusTag {
                text: card.part.key || ""
                presetColor: "#666a75"
            }
        }

        HusText {
            visible: !!card.part.description
            text: card.part.description || ""
            color: HusTheme.Primary.colorTextBase
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }
        HusText {
            visible: !!card.part.internal
            text: card.part.internal || ""
            color: HusTheme.Primary.colorTextSecondary
            font.pixelSize: 11
            Layout.fillWidth: true
            wrapMode: Text.WrapAnywhere
        }
    }
}
