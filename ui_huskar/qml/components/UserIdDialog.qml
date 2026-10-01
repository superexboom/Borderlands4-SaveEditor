// User ID 重试对话框：解密失败时由 AppBridge.userIdRequired 触发
import QtQuick
import HuskarUI.Basic

// 只替换 bodyDelegate：替换 contentDelegate 会连确定/取消按钮一起丢掉。
// 委托内的 id 在外面取不到，所以输入内容放在 dialog.userId 上。
HusModal {
    id: dialog
    objectName: "userIdDialog"

    property string filePath: ""
    property string lastError: ""
    property string userId: ""

    anchors.centerIn: parent
    width: 460
    closable: true
    confirmText: appBridge.trText("main_window.menu.open_selector")
    cancelText: appBridge.trText("main_window.dialogs.cancel")
    onConfirm: {
        var id = userId.trim();
        if (id === "")
            return;
        close();
        appBridge.openSave(filePath, id);
    }
    onCancel: {
        appBridge.toast(appBridge.trText("main_window.dialogs.open_cancelled"), "info");
        close();
    }

    bodyDelegate: Column {
        spacing: 10
        HusText {
            width: parent.width
            wrapMode: Text.Wrap
            color: HusTheme.Primary.colorTextBase
            text: appBridge.trText("main_window.dialogs.decrypt_failed_reason")
                  + "\n(" + dialog.lastError + ")\n\n"
                  + appBridge.trText("main_window.dialogs.enter_user_id")
        }
        HusInput {
            id: idInput
            objectName: "userIdInput"
            width: parent.width
            placeholderText: "Epic / Steam 64-bit ID"
            onTextChanged: dialog.userId = text
            Keys.onReturnPressed: dialog.confirm()
            Keys.onEnterPressed: dialog.confirm()
            Connections {
                target: dialog
                function onAboutToShow() { idInput.text = ""; }
                function onOpened() { idInput.forceActiveFocus(); }
            }
        }
    }

    Connections {
        target: appBridge
        function onUserIdRequired(path, error) {
            dialog.filePath = path;
            dialog.lastError = error;
            dialog.userId = "";
            dialog.title = appBridge.trText("main_window.dialogs.user_id_needed");
            dialog.open();
        }
    }
}
