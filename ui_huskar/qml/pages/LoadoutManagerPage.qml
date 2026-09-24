import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "../components"

// 配置管理器页：对齐主线 QtLoadoutManagerTab（已装备 + 配置槽 + 技能）
RowLayout {
    id: page
    anchors.fill: parent
    anchors.margins: 0
    spacing: 12

    readonly property var loc: vmLoadoutManager.strings
    readonly property var groupsLoc: loc.groups || ({})
    readonly property var buttonsLoc: loc.buttons || ({})

    Component.onCompleted: vmLoadoutManager.forceRefresh()

    // ---- 左：已装备物品 ----
    GlassPanel {
        Layout.fillWidth: true
        Layout.fillHeight: true

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8
            HusText { text: groupsLoc.equipped || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
            HusIconButton {
                visible: !vmLoadoutManager.liveMode
                text: buttonsLoc.read_save || ""
                iconSource: HusIcon.DownloadOutlined
                type: HusButton.Type_Primary
                onClicked: vmLoadoutManager.readSave()
            }
            HusText {
                visible: !vmLoadoutManager.saveLoaded
                text: (loc.placeholders || ({})).open_save_first || ""
                color: HusTheme.Primary.colorTextTertiary
                horizontalAlignment: Text.AlignHCenter
                Layout.fillWidth: true
            }
            LockedFlickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: width
                contentHeight: equippedColumn.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: HusScrollBar { }

                ColumnLayout {
                    id: equippedColumn
                    width: parent.width - 2
                    spacing: 6
                    Repeater {
                        model: vmLoadoutManager.equippedRows
                        delegate: Item {
                            Layout.fillWidth: true
                            Layout.preferredHeight: modelData.kind === "placeholder" ? phText.implicitHeight + 20 : rowCol.implicitHeight + 12

                            HusText {
                                id: phText
                                visible: modelData.kind === "placeholder"
                                anchors.centerIn: parent
                                width: parent.width
                                text: modelData.text || ""
                                color: HusTheme.Primary.colorTextTertiary
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.Wrap
                            }

                            Rectangle {
                                visible: modelData.kind === "item"
                                anchors.fill: parent
                                radius: 6
                                color: HusTheme.isDark ? "#1AFFFFFF" : "#0D000000"
                                ColumnLayout {
                                    id: rowCol
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 8
                                    spacing: 3
                                    RowLayout {
                                        spacing: 8
                                        HusText {
                                            Layout.preferredWidth: 90
                                            text: modelData.slot || ""
                                            font.bold: true
                                            font.pixelSize: 12
                                            color: HusTheme.Primary.colorTextBase
                                        }
                                        HusText {
                                            Layout.fillWidth: true
                                            text: modelData.name || ""
                                            font.pixelSize: 12
                                            color: HusTheme.Primary.colorTextBase
                                            elide: Text.ElideRight
                                        }
                                    }
                                    HusInput {
                                        Layout.fillWidth: true
                                        readOnly: true
                                        text: modelData.serial || ""
                                        font.pixelSize: 11
                                        font.family: "Consolas"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ---- 右：配置方案 + 技能 ----
    ColumnLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        spacing: 10

        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: loadoutColumn.implicitHeight + 24

            ColumnLayout {
                id: loadoutColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 12
                spacing: 8
                HusText { text: groupsLoc.loadout || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                RowLayout {
                    spacing: 6
                    Repeater {
                        model: vmLoadoutManager.slotButtons
                        delegate: HusButton {
                            text: String(modelData.slot)
                            type: modelData.active ? HusButton.Type_Primary : HusButton.Type_Default
                            contentDescription: modelData.tooltip
                            onClicked: vmLoadoutManager.selectSlot(modelData.slot)
                            Rectangle {
                                visible: modelData.hasSaved
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 3
                                width: 6
                                height: 6
                                radius: 3
                                color: "#4caf50"
                            }
                        }
                    }
                    HusText {
                        text: vmLoadoutManager.configNameText
                        color: HusTheme.Primary.colorTextSecondary
                        font.italic: true
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
                RowLayout {
                    spacing: 8
                    HusButton {
                        text: vmLoadoutManager.saveButtonText
                        enabled: vmLoadoutManager.canSaveLoadout && vmLoadoutManager.saveLoaded
                        onClicked: nameDialog.open()
                    }
                    HusButton {
                        text: vmLoadoutManager.loadButtonText
                        enabled: vmLoadoutManager.canLoad && vmLoadoutManager.saveLoaded
                        onClicked: vmLoadoutManager.loadLoadout()
                    }
                    HusButton {
                        visible: vmLoadoutManager.liveMode
                        text: buttonsLoc.review_live_recovery || ""
                        enabled: !appBridge.liveBusy
                        onClicked: vmLoadoutManager.reviewRecovery()
                    }
                    Item { Layout.fillWidth: true }
                }
            }
        }

        GlassPanel {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: vmLoadoutManager.skillsVisible

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8
                HusText { text: groupsLoc.skills || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: noticeText.implicitHeight + 16
                    visible: vmLoadoutManager.noticeText !== ""
                    radius: 6
                    color: "#1FFF9800"
                    border.color: "#59FF9800"
                    HusText {
                        id: noticeText
                        anchors.fill: parent
                        anchors.margins: 8
                        text: vmLoadoutManager.noticeText
                        color: "#e65100"
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                    }
                }
                LockedFlickable {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentWidth: width
                    contentHeight: skillsColumn.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: HusScrollBar { }

                    ColumnLayout {
                        id: skillsColumn
                        width: parent.width - 2
                        spacing: 4
                        Repeater {
                            model: vmLoadoutManager.skillRows
                            delegate: Item {
                                Layout.fillWidth: true
                                Layout.preferredHeight: modelData.kind === "placeholder" ? phText2.implicitHeight + 20
                                                       : modelData.kind === "header" ? 26 : 36

                                HusText {
                                    id: phText2
                                    visible: modelData.kind === "placeholder"
                                    anchors.centerIn: parent
                                    width: parent.width
                                    text: modelData.text || ""
                                    color: HusTheme.Primary.colorTextTertiary
                                    horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.Wrap
                                }

                                HusText {
                                    visible: modelData.kind === "header"
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.text || ""
                                    font.bold: true
                                    font.pixelSize: 13
                                    color: HusTheme.Primary.colorTextBase
                                }

                                Rectangle {
                                    visible: modelData.kind === "skill"
                                    anchors.fill: parent
                                    radius: 5
                                    color: HusTheme.isDark ? "#1AFFFFFF" : "#0D000000"
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 8
                                        anchors.rightMargin: 10
                                        spacing: 6
                                        Image {
                                            visible: modelData.iconUrl !== ""
                                            source: modelData.iconUrl || ""
                                            sourceSize.width: 24
                                            sourceSize.height: 24
                                        }
                                        HusText {
                                            Layout.fillWidth: true
                                            text: modelData.name || ""
                                            font.pixelSize: 12
                                            color: HusTheme.Primary.colorTextBase
                                            elide: Text.ElideRight
                                        }
                                        HusText {
                                            text: modelData.status || ""
                                            color: modelData.color || "#4caf50"
                                            font.bold: true
                                            font.pixelSize: 12
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ---- 配置名称输入 ----
    HusModal {
        id: nameDialog
        width: 420
        closable: true
        title: (loc.dialogs || ({})).name_prompt_title || ""
        confirmText: appBridge.trFormat("main_window.dialogs.confirm", {default: "OK"})
        cancelText: appBridge.trText("main_window.dialogs.cancel")
        onConfirm: { vmLoadoutManager.saveLoadout(nameInput.text); close(); }
        onCancel: close()
        contentDelegate: Item {
            implicitHeight: nameColumn.implicitHeight
            ColumnLayout {
                id: nameColumn
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: 10
                HusText {
                    text: (loc.dialogs || ({})).name_prompt_msg || ""
                    color: HusTheme.Primary.colorTextSecondary
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
                HusInput {
                    id: nameInput
                    Layout.fillWidth: true
                    placeholderText: (page.loc.labels || ({})).config_name || ""
                }
            }
        }
    }
}
