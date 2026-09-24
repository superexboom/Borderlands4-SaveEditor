// 应用级确认框：路由 AppBridge.confirmRequested → resolveConfirm
import QtQuick
import QtQuick.Layouts
import HuskarUI.Basic

HusModal {
    id: dialog

    property int confirmId: -1

    anchors.centerIn: parent
    width: 420
    closable: true
    confirmText: appBridge.trFormat("main_window.dialogs.confirm", {default: "OK"})
    cancelText: appBridge.trText("main_window.dialogs.cancel")
    onConfirm: { appBridge.resolveConfirm(confirmId, true); close(); }
    onCancel: { appBridge.resolveConfirm(confirmId, false); close(); }

    Connections {
        target: appBridge
        function onConfirmRequested(id, title, text, isWarning) {
            dialog.confirmId = id;
            dialog.title = title;
            dialog.description = text;
            dialog.open();
        }
    }
}
