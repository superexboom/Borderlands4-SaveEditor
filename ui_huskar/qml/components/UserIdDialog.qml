// User ID 重试对话框：解密失败时由 AppBridge.userIdRequired 触发
import QtQuick
import QtQuick.Layouts
import HuskarUI.Basic

HusModal {
    id: dialog

    property string filePath: ""
    property string lastError: ""

    anchors.centerIn: parent
    width: 460
    closable: true
    confirmText: appBridge.trText("main_window.menu.open_selector")
    cancelText: appBridge.trText("main_window.dialogs.cancel")
    onConfirm: {
        appBridge.openSave(filePath, idInput.text.trim());
        close();
    }
    onCancel: {
        appBridge.toast(appBridge.trText("main_window.dialogs.open_cancelled"), "info");
        close();
    }

    contentDelegate: Item {
        implicitHeight: contentColumn.implicitHeight
        ColumnLayout {
            id: contentColumn
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: 10
            HusText {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                color: HusTheme.Primary.colorTextBase
                text: appBridge.trText("main_window.dialogs.decrypt_failed_reason")
                      + "\n(" + dialog.lastError + ")\n\n"
                      + appBridge.trText("main_window.dialogs.enter_user_id")
            }
            HusInput {
                id: idInput
                Layout.fillWidth: true
                placeholderText: "Epic / Steam 64-bit ID"
            }
        }
    }

    Connections {
        target: appBridge
        function onUserIdRequired(path, error) {
            dialog.filePath = path;
            dialog.lastError = error;
            dialog.title = appBridge.trText("main_window.dialogs.user_id_needed");
            idInput.text = "";
            dialog.open();
        }
    }
}
