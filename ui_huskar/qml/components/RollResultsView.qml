// Roll 结果视图（装备四页/武器生成器“手气不错”共用）：左=结果卡片列表
// （间距+边框+稀有度色条），右=详情（稀有度本色标签、数值网格、图标词条、操作）。
// 对齐 GodRoll 详情的信息密度与主线 rollResultList/rollDetailCard 的视觉。
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic

RowLayout {
    id: view

    property var results: []
    property int currentIndex: results.length > 0 ? 0 : -1
    property var texts: ({})           // add_one/copy_base85/add_all/select_result
    property bool canAdd: true
    readonly property var current: (currentIndex >= 0 && currentIndex < results.length)
                                   ? results[currentIndex] : ({})

    signal addRequested(var indices)
    signal copyRequested(int index)

    onResultsChanged: currentIndex = results.length > 0 ? 0 : -1

    SelectionStyle { id: selStyle }
    spacing: 10

    // ---- 结果列表 ----
    LockedListView {
        Layout.preferredWidth: 330
        Layout.fillHeight: true
        clip: true
        spacing: 7
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: HusScrollBar { }
        model: view.results
        delegate: Item {
            id: rowDelegate
            width: ListView.view.width
            height: rowCol.implicitHeight + 18
            property bool selected: view.currentIndex === index
            Rectangle {
                anchors.fill: parent
                radius: 8
                color: rowDelegate.selected ? selStyle.bg
                     : rowHover.containsMouse ? (HusTheme.isDark ? "#1AFFFFFF" : "#0D000000")
                     : "transparent"
                border.color: rowDelegate.selected || rowHover.containsMouse
                            ? HusTheme.Primary.colorPrimary : selStyle.cardBorder
                border.width: 1
            }
            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.margins: 3
                width: 3
                radius: 2
                color: modelData.rarity_color || "transparent"
            }
            Column {
                id: rowCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 14
                anchors.rightMargin: 10
                spacing: 2
                HusText {
                    width: parent.width
                    text: modelData.name
                    font.bold: true
                    color: rowDelegate.selected ? selStyle.text : HusTheme.Primary.colorTextBase
                    elide: Text.ElideRight
                }
                HusText {
                    width: parent.width
                    text: modelData.manufacturer + " · " + modelData.weapon_type
                          + (modelData.element ? " · " + modelData.element : "")
                    color: rowDelegate.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
                HusText {
                    width: parent.width
                    visible: (modelData.rarity || "") !== ""
                    text: (modelData.rarity || "") + "  Lv" + (modelData.level || "?")
                    color: rowDelegate.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }
            MouseArea {
                id: rowHover
                anchors.fill: parent
                hoverEnabled: true
                onClicked: view.currentIndex = index
            }
        }
    }

    // ---- 详情 ----
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
                spacing: 8
                HusText {
                    Layout.fillWidth: true
                    text: view.current.name || (view.texts.select_result || "—")
                    font.bold: true
                    font.pixelSize: 16
                    color: HusTheme.Primary.colorTextBase
                    elide: Text.ElideRight
                }
                HusTag {
                    visible: (view.current.rarity || "") !== ""
                    text: view.current.rarity || ""
                    presetColor: view.current.rarity_color || "#78909C"
                }
                HusText {
                    visible: (view.current.level || "") !== ""
                    text: "Lv" + (view.current.level || "?")
                    color: HusTheme.Primary.colorTextSecondary
                }
            }
            HusText {
                visible: view.current.name !== undefined
                text: (view.current.manufacturer || "") + " · " + (view.current.weapon_type || "")
                      + (view.current.element ? " · " + view.current.element : "")
                color: HusTheme.Primary.colorTextSecondary
                font.pixelSize: 12
            }
            RowLayout {
                visible: view.current.name !== undefined
                spacing: 8
                HusButton {
                    text: view.texts.add_one || "Add"
                    type: HusButton.Type_Primary
                    enabled: view.canAdd
                    onClicked: view.addRequested([view.currentIndex])
                }
                HusButton {
                    text: view.texts.copy_base85 || "Copy Base85"
                    onClicked: view.copyRequested(view.currentIndex)
                }
                Item { Layout.fillWidth: true }
            }

            // 数值网格（标签上数值下，对齐主线 rollStatCell）
            GridLayout {
                Layout.fillWidth: true
                visible: view.current.name !== undefined && (view.current.stats || []).length > 0
                columns: Math.max(1, Math.min(4, (view.current.stats || []).length))
                columnSpacing: 8
                rowSpacing: 6
                Repeater {
                    model: view.current.stats || []
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: statCol.implicitHeight + 12
                        radius: 6
                        color: HusTheme.isDark ? "#22FFFFFF" : "#11000000"
                        Column {
                            id: statCol
                            anchors.centerIn: parent
                            spacing: 1
                            HusText {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.label
                                color: HusTheme.Primary.colorTextSecondary
                                font.pixelSize: 11
                            }
                            HusText {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.value
                                color: HusTheme.Primary.colorTextBase
                                font.bold: true
                                font.pixelSize: 14
                            }
                        }
                    }
                }
            }

            // 图标词条（与 GodRoll 详情/物品页装备卡同一风格）
            Repeater {
                model: view.current.effect_entries || []
                delegate: Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: effectRow.implicitHeight + 12
                    radius: 6
                    color: HusTheme.isDark ? "#22FFFFFF" : "#11000000"
                    RowLayout {
                        id: effectRow
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 6
                        spacing: 8
                        Rectangle {
                            visible: (modelData.icon || "") !== ""
                            Layout.preferredWidth: 34
                            Layout.preferredHeight: 34
                            Layout.alignment: Qt.AlignTop
                            radius: 4
                            color: "#164653"
                            Image {
                                anchors.centerIn: parent
                                source: modelData.icon || ""
                                sourceSize.width: 30
                                sourceSize.height: 30
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            HusText {
                                text: modelData.title
                                font.bold: true
                                color: modelData.legendary ? "#E8A33D" : "#39BCE8"
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                            HusText {
                                visible: (modelData.description || "") !== ""
                                text: modelData.description
                                color: HusTheme.Primary.colorTextSecondary
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }
            Item { Layout.preferredHeight: 4 }
        }
    }
}
