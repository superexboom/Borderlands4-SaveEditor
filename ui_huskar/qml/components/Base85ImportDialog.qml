import QtQuick
import HuskarUI.Basic

// Base85 粘贴导入对话框（职业模组 / 强化 / 装备页共用）。
// 只替换 bodyDelegate：替换 contentDelegate 会连标题和确定/取消按钮一起丢掉。
// 委托内的 id 在外面取不到，所以输入内容放在 dialog.text 上。
HusModal {
    id: dialog
    objectName: "base85Dialog"
    property string text: ""
    signal submitted(string serial)

    width: 560
    closable: true
    confirmText: appBridge.trFormat("main_window.dialogs.confirm", {default: "OK"})
    cancelText: appBridge.trText("main_window.dialogs.cancel")
    onAboutToShow: text = ""
    onCancel: close()
    onConfirm: {
        var serial = text.trim();
        if (serial === "")
            return;
        close();
        submitted(serial);
    }

    bodyDelegate: Column {
        spacing: 8
        HusText {
            width: parent.width
            visible: dialog.description !== ""
            text: dialog.description
            color: dialog.colorDescription
            wrapMode: Text.Wrap
        }
        HusInput {
            id: input
            objectName: "base85Input"
            width: parent.width
            placeholderText: "@U..."
            onTextChanged: dialog.text = text
            Keys.onReturnPressed: dialog.confirm()
            Keys.onEnterPressed: dialog.confirm()
            Connections {
                target: dialog
                function onAboutToShow() { input.text = ""; }
                function onOpened() { input.forceActiveFocus(); }
            }
        }
    }
}
