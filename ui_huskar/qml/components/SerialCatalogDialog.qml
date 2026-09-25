// 内置 / NPC / 任务序列目录浏览器（对齐主线 _EmbeddedCatalogDialog）
// 由 SerialInspectorPage 在 vmSerialInspector.openCatalog() 返回 true 后 open()。
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "CopyKeys.js" as CopyKeys

HusModal {
    id: dialog

    property var loc: ({})
    property int currentEntry: -1

    width: 980
    height: 650
    closable: true
    maskClosable: true

    SelectionStyle { id: selStyle }

    onVisibleChanged: {
        if (visible)
            dialog.currentEntry = -1;
    }

    contentDelegate: Item {
        // HusModal 的内容 Loader 高度跟随内容 implicitHeight（Item 默认 0），
        // 不显式给高整个弹窗内容会塌成 0 高、所有行叠在一起
        implicitHeight: 590
        // searchInput 的 id 作用域在本委托组件内，重置逻辑必须放在这里
        // （此前在弹窗根 onVisibleChanged 引用 searchInput → ReferenceError，按钮打不开弹窗）
        Connections {
            target: dialog
            function onVisibleChanged() {
                if (dialog.visible) searchInput.text = "";
            }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                HusText {
                    text: dialog.loc && dialog.loc.title ? dialog.loc.title : "Internal / NPC / Mission presets"
                    font.pixelSize: 16
                    font.bold: true
                    color: HusTheme.Primary.colorTextBase
                }
                Item { Layout.fillWidth: true }
                HusIconButton {
                    iconSource: HusIcon.CloseOutlined
                    contentDescription: dialog.loc && dialog.loc.close ? dialog.loc.close : "Close"
                    onClicked: dialog.close()
                }
            }

            HusText {
                text: dialog.loc && dialog.loc.warning ? dialog.loc.warning : ""
                color: "#FFB74D"
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }

            HusInput {
                id: searchInput
                Layout.fillWidth: true
                placeholderText: dialog.loc && dialog.loc.search ? dialog.loc.search : ""
                onTextChanged: vmSerialInspector.catalogFilter(text)
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 8

                LockedListView {
                    id: entryList
                    Layout.preferredWidth: 440
                    Layout.fillHeight: true
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    model: vmSerialInspector.catalogRows
                    ScrollBar.vertical: HusScrollBar { }
                    activeFocusOnTab: true

                    // Ctrl+C 复制选中条目的 Base85（与 Copy 按钮同一路径）
                    Keys.onPressed: function(event) {
                        if (CopyKeys.matchCopy(event))
                            vmSerialInspector.catalogCopy(dialog.currentEntry);
                    }

                    delegate: Item {
                        width: entryList.width
                        height: modelData && modelData.rowType === "group" ? 30 : 44

                        Rectangle {
                            anchors.fill: parent
                            color: modelData.rowType === "group"
                                   ? (HusTheme.isDark ? "#33FFFFFF" : "#22000000")
                                   : (dialog.currentEntry === modelData.entryIndex
                                      ? selStyle.bg : "transparent")
                        }

                        HusText {
                            visible: modelData.rowType === "group"
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.leftMargin: 6
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.title || ""
                            font.bold: true
                            color: HusTheme.Primary.colorTextBase
                            elide: Text.ElideRight
                        }

                        Column {
                            visible: modelData.rowType === "entry"
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 1
                            HusText {
                                width: parent.width
                                text: (modelData.name || "") + (modelData.level ? "  ·Lv" + modelData.level : "")
                                color: dialog.currentEntry === modelData.entryIndex ? selStyle.text : HusTheme.Primary.colorTextBase
                                elide: Text.ElideRight
                            }
                            HusText {
                                width: parent.width
                                text: [modelData.typeText, modelData.context].filter(Boolean).join(" · ")
                                color: dialog.currentEntry === modelData.entryIndex ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                        }

                        MouseArea {
                            visible: modelData.rowType === "entry"
                            anchors.fill: parent
                            onClicked: {
                                dialog.currentEntry = modelData.entryIndex;
                                entryList.forceActiveFocus();
                                vmSerialInspector.catalogSelect(modelData.entryIndex);
                            }
                            onDoubleClicked: {
                                dialog.currentEntry = modelData.entryIndex;
                                if (vmSerialInspector.catalogLoad(modelData.entryIndex))
                                    dialog.close();
                            }
                        }
                    }

                    EmptyHint {
                        anchors.fill: parent
                        visible: vmSerialInspector.catalogRows.length === 0
                        description: dialog.loc && dialog.loc.no_selection ? dialog.loc.no_selection : ""
                    }
                }

                Rectangle {
                    Layout.fillHeight: true
                    width: 1
                    color: HusTheme.isDark ? "#66505060" : "#59B4B4C8"
                }

                LockedFlickable {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentWidth: width
                    contentHeight: detailText.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: HusScrollBar { }

                    Text {
                        id: detailText
                        width: parent.width
                        textFormat: Text.RichText
                        wrapMode: Text.WordWrap
                        color: HusTheme.Primary.colorTextBase
                        text: vmSerialInspector.catalogDetailHtml
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                HusIconButton {
                    text: dialog.loc && dialog.loc.load ? dialog.loc.load : "Inspect"
                    iconSource: HusIcon.SearchOutlined
                    type: HusButton.Type_Primary
                    enabled: vmSerialInspector.catalogCanLoad
                    onClicked: {
                        if (vmSerialInspector.catalogLoad(dialog.currentEntry))
                            dialog.close();
                    }
                }
                HusIconButton {
                    text: dialog.loc && dialog.loc.copy ? dialog.loc.copy : "Copy Base85"
                    iconSource: HusIcon.CopyOutlined
                    enabled: vmSerialInspector.catalogCanCopy
                    onClicked: vmSerialInspector.catalogCopy(dialog.currentEntry)
                }
                HusIconButton {
                    text: dialog.loc && dialog.loc.add ? dialog.loc.add : "Add to backpack"
                    iconSource: HusIcon.PlusOutlined
                    enabled: vmSerialInspector.catalogCanAdd
                    onClicked: vmSerialInspector.catalogAdd(dialog.currentEntry)
                }
                Item { Layout.fillWidth: true }
                HusIconButton {
                    text: dialog.loc && dialog.loc.close ? dialog.loc.close : "Close"
                    onClicked: dialog.close()
                }
            }
        }
    }
}
