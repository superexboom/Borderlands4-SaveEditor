import QtQuick
import QtQuick.Layouts
import HuskarUI.Basic
import "../components"

// 选择存档页：对齐主线 SaveSelectorWidget 的布局与行为
ColumnLayout {
    id: page
    anchors.fill: parent
    anchors.margins: 0
    spacing: 10

    readonly property var loc: vmSelectSave.strings

    Component.onCompleted: vmSelectSave.refresh()

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.refresh : "Refresh"
            iconSource: HusIcon.ReloadOutlined
            onClicked: vmSelectSave.refresh()
        }
        HusIconButton {
            text: page.loc.buttons ? (page.loc.buttons.select_game_dir || "Set Game Directory") : "Set Game Directory"
            iconSource: HusIcon.FolderOpenOutlined
            onClicked: vmSelectSave.selectGameDir()
        }
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.select_save_folder : "Select Save Folder"
            iconSource: HusIcon.FolderOpenOutlined
            onClicked: vmSelectSave.selectSaveFolder()
        }
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.select_backup_folder : "Select Backup Folder"
            iconSource: HusIcon.FolderOpenOutlined
            onClicked: vmSelectSave.selectBackupFolder()
        }
        Item { Layout.fillWidth: true }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        HusText {
            text: page.loc.labels ? page.loc.labels.user_id_input : "Manual User ID:"
            color: HusTheme.Primary.colorTextBase
        }
        HusInput {
            Layout.fillWidth: true
            text: vmSelectSave.userId
            placeholderText: page.loc.placeholders ? page.loc.placeholders.user_id_input : ""
            onTextEdited: vmSelectSave.setUserId(text)
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 2
        HusText { text: vmSelectSave.gameDirText; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 12; elide: Text.ElideMiddle; Layout.fillWidth: true }
        HusText { text: vmSelectSave.savePathText; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 12; elide: Text.ElideMiddle; Layout.fillWidth: true }
        HusText { text: vmSelectSave.backupPathText; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 12; elide: Text.ElideMiddle; Layout.fillWidth: true }
    }

    GlassPanel {
        Layout.fillWidth: true
        Layout.fillHeight: true

        HusTableView {
                id: table
                anchors.fill: parent
                initModel: vmSelectSave.saves
                columns: [
                    { title: page.loc.headers ? page.loc.headers.file : "File", dataIndex: "name", width: 120, delegate: cellDelegate },
                    { title: page.loc.headers ? page.loc.headers.user_id : "User ID", dataIndex: "id", width: 170, delegate: cellDelegate },
                    { title: page.loc.headers ? page.loc.headers.modified : "Modified", dataIndex: "modified", width: 150, delegate: cellDelegate },
                    { title: page.loc.headers ? page.loc.headers.size : "Size", dataIndex: "size_kb", width: 80, delegate: sizeDelegate },
                    { title: page.loc.headers ? page.loc.headers.path : "Path", dataIndex: "full_path", width: 420, minimumWidth: 160, delegate: cellDelegate }
                ]
                minimumRowHeight: 34
                maximumRowHeight: 44
                showRowHeader: false
                alternatingRow: true
                columnResizable: true
                onCheckedKeysChanged: {
                    if (checkedKeys.length > 0)
                        vmSelectSave.selectRow(parseInt(checkedKeys[checkedKeys.length - 1]));
                }
            }
        EmptyHint {
            anchors.fill: parent
            visible: vmSelectSave.saves.length === 0
            description: page.loc.labels ? page.loc.labels.status_no_saves : "No save files found."
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        HusText {
            text: vmSelectSave.statusText
            color: HusTheme.Primary.colorTextSecondary
            Layout.fillWidth: true
            elide: Text.ElideMiddle
        }
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.open : "Open"
            type: HusButton.Type_Primary
            iconSource: HusIcon.SelectOutlined
            onClicked: vmSelectSave.openSelected()
        }
    }

    Component {
        id: cellDelegate
        Item {
            anchors.fill: parent
            HusText {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 6
                text: String(cellData === undefined || cellData === null ? "" : cellData)
                color: HusTheme.Primary.colorTextBase
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideMiddle
            }
            MouseArea {
                anchors.fill: parent
                onClicked: table.checkedKeys = [String(row)]
                onDoubleClicked: vmSelectSave.openRow(row)
            }
        }
    }

    Component {
        id: sizeDelegate
        Item {
            anchors.fill: parent
            HusText {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 6
                text: Number(cellData).toFixed(1) + " KB"
                color: HusTheme.Primary.colorTextBase
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            MouseArea {
                anchors.fill: parent
                onClicked: table.checkedKeys = [String(row)]
                onDoubleClicked: vmSelectSave.openRow(row)
            }
        }
    }
}
