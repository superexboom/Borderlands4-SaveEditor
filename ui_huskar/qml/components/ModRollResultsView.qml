import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic

// 职业模组/强化模组 Roll 结果：左侧结果列表，右侧按构筑类型展示技能与词条。
RowLayout {
    id: view
    property var results: []
    property var texts: ({})
    property bool canAdd: true
    property int currentIndex: results.length > 0 ? 0 : -1
    readonly property var current: currentIndex >= 0 && currentIndex < results.length
                                  ? results[currentIndex] : ({})
    signal addRequested(var indices)
    signal copyRequested(int index)
    onResultsChanged: currentIndex = results.length > 0 ? 0 : -1

    SelectionStyle { id: selStyle }
    spacing: 10

    LockedListView {
        Layout.preferredWidth: 300
        Layout.fillHeight: true
        clip: true
        spacing: 7
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: HusScrollBar { }
        model: view.results
        delegate: Item {
            id: summaryDelegate
            width: ListView.view.width
            height: summaryColumn.implicitHeight + 18
            property bool selected: view.currentIndex === index
            Rectangle {
                anchors.fill: parent
                radius: 8
                color: summaryDelegate.selected ? selStyle.bg : "transparent"
                border.color: summaryDelegate.selected ? HusTheme.Primary.colorPrimary : selStyle.cardBorder
                border.width: 1
            }
            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.margins: 3
                width: 3
                radius: 2
                color: modelData.status === "legal" ? "#52b879" : "#e6a439"
            }
            Column {
                id: summaryColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 14
                anchors.rightMargin: 10
                spacing: 2
                HusText {
                    width: parent.width
                    text: modelData.name || "—"
                    font.bold: true
                    color: summaryDelegate.selected ? selStyle.text : HusTheme.Primary.colorTextBase
                    elide: Text.ElideRight
                }
                HusText {
                    width: parent.width
                    text: (modelData.manufacturer || "") + " · " + (modelData.rarity || "")
                    color: summaryDelegate.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
                HusText {
                    width: parent.width
                    text: (modelData.statusLabel || "") + " · Lv" + (modelData.level || "?")
                    color: summaryDelegate.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }
            MouseArea {
                id: summaryHover
                anchors.fill: parent
                hoverEnabled: true
                onClicked: view.currentIndex = index
            }
        }
    }

    LockedFlickable {
        Layout.fillWidth: true
        Layout.fillHeight: true
        contentWidth: width
        contentHeight: detailColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: HusScrollBar { }
        ColumnLayout {
            id: detailColumn
            width: parent.width - 2
            spacing: 8
            RowLayout {
                Layout.fillWidth: true
                HusText {
                    Layout.fillWidth: true
                    text: view.current.name || (view.texts.select_result || "—")
                    font.bold: true
                    font.pixelSize: 16
                    color: HusTheme.Primary.colorTextBase
                    elide: Text.ElideRight
                }
                HusTag {
                    visible: !!view.current.statusLabel
                    text: view.current.statusLabel || ""
                    presetColor: view.current.status === "legal" ? "green" : "orange"
                }
            }
            HusText {
                visible: !!view.current.manufacturer
                text: (view.current.manufacturer || "") + " · " + (view.current.rarity || "") + " · Lv" + (view.current.level || "?")
                color: HusTheme.Primary.colorTextSecondary
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true
                HusButton {
                    text: view.texts.add_one || "Add"
                    type: HusButton.Type_Primary
                    enabled: view.canAdd && view.currentIndex >= 0
                    onClicked: view.addRequested([view.currentIndex])
                }
                HusButton {
                    text: view.texts.copy || "Copy"
                    enabled: view.currentIndex >= 0
                    onClicked: view.copyRequested(view.currentIndex)
                }
                Item { Layout.fillWidth: true }
            }

            ModRollSection {
                visible: (view.current.legendary || "") !== ""
                title: view.texts.legendary || "Legendary bonus"
                entries: view.current.legendary ? [{"level": "", "title": view.current.legendary, "description": view.current.legendary_detail || "", "accent": "#e6a439"}] : []
            }
            ModRollSection {
                visible: (view.current.skills || []).length > 0
                title: view.texts.skills || "Skills"
                entries: view.current.skills || []
            }
            ModRollSection {
                visible: (view.current.core || []).length > 0
                title: view.texts.core || "Core perks"
                entries: view.current.core || []
            }
            ModRollSection {
                visible: (view.current.perks || []).length > 0
                title: view.texts.perks || "Perks"
                entries: view.current.perks || []
            }
            ModRollSection {
                visible: (view.current.stats || []).length > 0
                title: view.texts.stats || "Secondary stats"
                entries: view.current.stats || []
            }
            ModRollSection {
                visible: (view.current.firmware || []).length > 0
                title: view.texts.firmware || "Firmware"
                entries: view.current.firmware || []
            }
            Item { Layout.preferredHeight: 4 }
        }
    }
}
