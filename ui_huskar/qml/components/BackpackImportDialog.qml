import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import HuskarUI.Basic

HusModal {
    id: dialog
    objectName: "backpackDialog"
    property var vm: null
    // Read the language first so the binding re-evaluates on a language switch.
    function tr(path) {
        var language = appBridge.language;
        return appBridge.trText(path);
    }
    property int selectedSource: -1
    property string query: ""
    title: vm ? vm.sourceTexts.backpack_title || vm.sourceTexts.backpack : ""
    width: Math.min(820, parent ? parent.width - 32 : 820)
    height: Math.min(600, parent ? parent.height - 32 : 600)
    colorBg: HusTheme.isDark ? "#1f242d" : "#f7f8fa"
    closable: true
    function filtered() {
        var items = vm ? vm.backpackItems : [];
        var result = [];
        for (var i = 0; i < items.length; ++i) {
            var item = items[i];
            if ((item.name + " " + item.detail).toLowerCase().indexOf(query.toLowerCase()) >= 0)
                result.push({sourceIndex:i, name:item.name, detail:item.detail});
        }
        return result;
    }
    function importSelection() {
        if (selectedSource < 0) return;
        vm.importBackpackItem(selectedSource);
        close();
    }
    SelectionStyle { id: style }
    contentDelegate: Item {
        implicitHeight: dialog.height - 4
        Connections {
            target: dialog
            function onAboutToShow() { dialog.query = ""; search.text = ""; dialog.selectedSource = -1; }
            function onOpened() { search.forceActiveFocus(); }
        }
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12
            RowLayout {
                HusText { Layout.fillWidth: true; text: dialog.title; font.pixelSize: 18; font.bold: true; color: HusTheme.Primary.colorTextBase }
                HusText { text: dialog.filtered().length + " / " + (dialog.vm ? dialog.vm.backpackItems.length : 0); color: HusTheme.Primary.colorTextSecondary }
                HusIconButton { iconSource: HusIcon.CloseOutlined; contentDescription: "Close"; onClicked: dialog.close() }
            }
            HusInput {
                id: search
                objectName: "backpackSearch"
                Layout.fillWidth: true
                placeholderText: dialog.tr("backpack_import.search")
                onTextChanged: { dialog.query = text; dialog.selectedSource = -1; }
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: style.cardBg
                border.color: style.cardBorder
                radius: 10
                LockedListView {
                    id: list
                    objectName: "backpackResults"
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 6
                    model: dialog.filtered()
                    ScrollBar.vertical: HusScrollBar {}
                    Keys.onReturnPressed: dialog.importSelection()
                    onCurrentIndexChanged: if (currentIndex >= 0 && currentIndex < model.length) dialog.selectedSource = model[currentIndex].sourceIndex
                    delegate: Rectangle {
                        width: list.width
                        height: 68
                        radius: 8
                        color: dialog.selectedSource === modelData.sourceIndex ? style.bgSubtle : mouse.containsMouse ? style.hover : "transparent"
                        border.color: dialog.selectedSource === modelData.sourceIndex ? "#4a90e2" : style.cardBorder
                        Column {
                            anchors.fill: parent; anchors.margins: 12; spacing: 4
                            HusText { width: parent.width; text: modelData.name; font.pixelSize: 16; font.bold: true; color: HusTheme.Primary.colorTextBase; elide: Text.ElideRight }
                            HusText { width: parent.width; text: modelData.detail; font.pixelSize: 12; color: HusTheme.Primary.colorTextSecondary; elide: Text.ElideRight }
                        }
                        MouseArea {
                            id: mouse; anchors.fill: parent; hoverEnabled: true
                            onClicked: { list.currentIndex = index; dialog.selectedSource = modelData.sourceIndex; list.forceActiveFocus(); }
                            onDoubleClicked: { dialog.selectedSource = modelData.sourceIndex; dialog.importSelection(); }
                        }
                    }
                    EmptyHint { anchors.centerIn: parent; visible: list.count === 0; description: dialog.tr("backpack_import.empty") }
                }
            }
            RowLayout {
                HusText { Layout.fillWidth: true; text: dialog.tr("backpack_import.hint"); color: HusTheme.Primary.colorTextSecondary }
                HusButton { text: dialog.tr("main_window.dialogs.cancel"); onClicked: dialog.close() }
                HusButton { objectName: "backpackConfirm"; text: dialog.tr("backpack_import.import_selected"); type: HusButton.Type_Primary; enabled: dialog.selectedSource >= 0; onClicked: dialog.importSelection() }
            }
        }
    }
}
