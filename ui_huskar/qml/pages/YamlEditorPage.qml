import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "../components"
import "../components/CopyKeys.js" as CopyKeys

// YAML 编辑器页：对齐主线 QtYamlEditorTab（树/源码/分屏 + 检查器 + 搜索 + 对比 + 撤销）
ColumnLayout {
    id: page
    anchors.fill: parent
    anchors.margins: 0
    spacing: 8

    readonly property var loc: vmYamlEditor.strings
    readonly property var btnLoc: loc.buttons || ({})
    readonly property var opsLoc: loc.ops || ({})
    readonly property var insLoc: loc.inspector || ({})

    // 焦点列（Ctrl+C 复制目标："key" 复制路径 / "value" 复制值）
    property string focusedColumn: "value"

    SelectionStyle { id: selStyle }

    Component.onCompleted: {
        vmYamlEditor.sync_from_controller();
    }

    // ---- 工具栏 ----
    RowLayout {
        Layout.fillWidth: true
        spacing: 6
        HusInput {
            Layout.preferredWidth: 240
            placeholderText: (loc.search || ({})).placeholder || ""
            onTextChanged: vmYamlEditor.setSearchText(text)
            onAccepted: vmYamlEditor.cycleSearch(1)
        }
        HusText {
            Layout.preferredWidth: 56
            text: vmYamlEditor.searchCountText
            color: HusTheme.Primary.colorTextSecondary
        }
        HusButton { text: "↑"; onClicked: vmYamlEditor.cycleSearch(-1) }
        HusButton { text: "↓"; onClicked: vmYamlEditor.cycleSearch(1) }
        Item { Layout.preferredWidth: 10 }
        HusButton {
            text: btnLoc.tree_view || ""
            checkable: true
            checked: vmYamlEditor.viewMode === 0
            onClicked: vmYamlEditor.setViewMode(0)
        }
        HusButton {
            text: btnLoc.source_view || ""
            checkable: true
            checked: vmYamlEditor.viewMode === 1
            onClicked: vmYamlEditor.setViewMode(1)
        }
        HusButton {
            text: btnLoc.split_view || ""
            checkable: true
            checked: vmYamlEditor.viewMode === 2
            onClicked: vmYamlEditor.setViewMode(2)
        }
        Item { Layout.preferredWidth: 10 }
        HusButton { text: "↩"; enabled: vmYamlEditor.canUndo; onClicked: vmYamlEditor.undo() }
        HusButton { text: "↪"; enabled: vmYamlEditor.canRedo; onClicked: vmYamlEditor.redo() }
        Item { Layout.preferredWidth: 10 }
        HusButton {
            text: vmYamlEditor.diffButtonText
            checkable: true
            checked: vmYamlEditor.diffEnabled
            onToggled: vmYamlEditor.setDiffEnabled(checked)
        }
        Item { Layout.fillWidth: true }
    }

    EmptyHint {
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: !vmYamlEditor.saveLoaded
        description: appBridge.trText("main_window.dialogs.load_save_first")
    }

    // ---- 主区域 ----
    RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: vmYamlEditor.saveLoaded
        spacing: 10

        // 树
        GlassPanel {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: vmYamlEditor.viewMode !== 1

            LockedListView {
                id: treeList
                anchors.fill: parent
                anchors.margins: 4
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: HusScrollBar { }
                model: vmYamlEditor.rows
                cacheBuffer: 2000
                activeFocusOnTab: true

                // Ctrl+C 复制选中行的焦点列（key=路径 / value=值）
                Keys.onPressed: function(event) {
                    if (CopyKeys.matchCopy(event)) {
                        if (page.focusedColumn === "key")
                            vmYamlEditor.copyPath(treeList.currentIndex);
                        else
                            vmYamlEditor.copyValue(treeList.currentIndex);
                    }
                }

                Connections {
                    target: vmYamlEditor
                    function onRevealRequested(row) {
                        treeList.currentIndex = row;
                        treeList.positionViewAtIndex(row, ListView.Center);
                    }
                }

                delegate: Item {
                    width: treeList.width
                    height: 26
                    Rectangle {
                        id: rowRect
                        anchors.fill: parent
                        property bool selected: treeList.currentIndex === index
                        color: selected
                               ? selStyle.bg
                               : modelData.change === "added" ? "#1A78DBA9"
                               : modelData.change === "modified" ? "#1AEF9F27"
                               : "transparent"
                        radius: 3
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 4 + modelData.depth * 16
                            spacing: 6
                            HusText {
                                Layout.preferredWidth: 14
                                visible: modelData.isContainer
                                text: modelData.expanded ? "▾" : "▸"
                                color: rowRect.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary
                            }
                            HusText {
                                Layout.preferredWidth: 220
                                text: modelData.key
                                color: rowRect.selected ? selStyle.text : HusTheme.Primary.colorTextBase
                                elide: Text.ElideRight
                                MouseArea {
                                    anchors.fill: parent
                                    propagateComposedEvents: true
                                    onClicked: function(mouse) { mouse.accepted = false; }
                                    onDoubleClicked: {
                                        if (!modelData.isIntKey) {
                                            renameInput.text = modelData.key;
                                            renameInput.row = index;
                                            renameInput.visible = true;
                                            renameInput.forceActiveFocus();
                                        }
                                    }
                                }
                                HusInput {
                                    id: renameInput
                                    objectName: "yamlInlineEditor"
                                    property int row: -1
                                    anchors.fill: parent
                                    visible: false
                                    // 回车和失焦都会发 editingFinished：先清 row，清焦点时再触发也不会重复提交
                                    onEditingFinished: {
                                        const target = row;
                                        row = -1;
                                        if (target >= 0)
                                            vmYamlEditor.renameKey(target, text);
                                        focus = false;
                                        visible = false;
                                    }
                                    onActiveFocusChanged: if (!activeFocus) visible = false
                                }
                            }
                            HusText {
                                Layout.fillWidth: true
                                visible: !modelData.isContainer && valueEditor.row !== index
                                text: modelData.valueText
                                color: rowRect.selected ? selStyle.secondaryText
                                     : modelData.valueType === "int" || modelData.valueType === "float" ? "#7ee787"
                                     : modelData.valueType === "bool" ? "#79c0ff"
                                     : modelData.valueType === "null" ? "#a0a0a8"
                                     : HusTheme.Primary.colorTextSecondary
                                elide: Text.ElideRight
                                MouseArea {
                                    anchors.fill: parent
                                    propagateComposedEvents: true
                                    onClicked: function(mouse) { mouse.accepted = false; }
                                    onDoubleClicked: {
                                        valueEditor.row = index;
                                        valueEditor.initialText = modelData.valueText;
                                        valueEditor.visible = true;
                                        valueEditor.forceActiveFocus();
                                    }
                                }
                            }
                            HusInput {
                                id: valueEditor
                                objectName: "yamlInlineEditor"
                                property int row: -1
                                property string initialText: ""
                                Layout.fillWidth: true
                                visible: row === index
                                text: initialText
                                onEditingFinished: {
                                    const target = row;
                                    row = -1;
                                    if (target >= 0)
                                        vmYamlEditor.editValue(target, text);
                                    focus = false;
                                    visible = false;
                                }
                                onActiveFocusChanged: if (!activeFocus && row === index) { row = -1; visible = false; }
                            }
                            HusText {
                                Layout.preferredWidth: 160
                                text: modelData.annotation
                                color: rowRect.selected ? selStyle.tertiaryText : HusTheme.Primary.colorTextTertiary
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            propagateComposedEvents: true
                            onClicked: function(mouse) {
                                // 键名 / 值输入框失焦即提交，提交会重建行模型、销毁本 delegate：
                                // 这次点击只结束编辑，不再读 modelData / index。
                                // 输入框在 treeList 这个焦点域里，forceActiveFocus 列表会把焦点
                                // 还给输入框本身，所以直接清掉它的 focus（焦点留在列表上）。
                                const focused = page.Window.activeFocusItem;
                                if (focused && focused.objectName === "yamlInlineEditor") {
                                    mouse.accepted = false;
                                    focused.focus = false;
                                    return;
                                }
                                vmYamlEditor.selectRow(index);
                                treeList.currentIndex = index;
                                // 键列（缩进箭头+键名 220）之内聚焦 key 列，其余聚焦 value 列
                                page.focusedColumn = mouse.x <= (4 + modelData.depth * 16 + 240) ? "key" : "value";
                                treeList.forceActiveFocus();
                                if (modelData.isContainer)
                                    vmYamlEditor.toggleRow(index);
                                if (mouse.button === Qt.RightButton)
                                    contextMenu.openFor(index);
                                mouse.accepted = false;
                            }
                        }
                    }
                }
            }
        }

        // 检查器
        GlassPanel {
            Layout.preferredWidth: 380
            Layout.fillHeight: true
            visible: vmYamlEditor.viewMode === 0

            LockedFlickable {
                anchors.fill: parent
                contentWidth: width
                contentHeight: insColumn.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: HusScrollBar { }

                ColumnLayout {
                    id: insColumn
                    width: parent.width - 2
                    spacing: 10

                    HusText { text: insLoc.path || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: crumbText.implicitHeight + 12
                        radius: 6
                        color: HusTheme.isDark ? "#3a3a45" : "#F1EFE8"
                        HusText {
                            id: crumbText
                            anchors.fill: parent
                            anchors.margins: 6
                            text: vmYamlEditor.breadcrumbText
                            color: HusTheme.Primary.colorTextBase
                            wrapMode: Text.Wrap
                            font.family: "Consolas"
                        }
                    }

                    GlassPanel {
                        Layout.fillWidth: true
                        Layout.preferredHeight: serialColumn.implicitHeight + 20
                        visible: vmYamlEditor.serialInfoVisible
                        ColumnLayout {
                            id: serialColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 10
                            spacing: 6
                            HusText { text: insLoc.serial_title || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                            HusText {
                                text: vmYamlEditor.serialInfoText
                                color: HusTheme.Primary.colorTextSecondary
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                            HusButton {
                                text: insLoc.open_in_editor || ""
                                onClicked: vmYamlEditor.openInItemEditor()
                            }
                        }
                    }

                    GlassPanel {
                        Layout.fillWidth: true
                        Layout.preferredHeight: opsColumn.implicitHeight + 20
                        ColumnLayout {
                            id: opsColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 10
                            spacing: 6
                            HusText { text: insLoc.ops_title || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                            GridLayout {
                                Layout.fillWidth: true
                                columns: 3
                                columnSpacing: 6
                                rowSpacing: 6
                                HusButton { Layout.fillWidth: true; text: opsLoc.add_child || ""; onClicked: addChildDialog.open() }
                                HusButton { Layout.fillWidth: true; text: opsLoc.rename || ""; onClicked: renameDialog.open() }
                                HusButton { Layout.fillWidth: true; text: opsLoc.duplicate || ""; onClicked: vmYamlEditor.duplicateRow(treeList.currentIndex) }
                                HusButton { Layout.fillWidth: true; text: opsLoc.copy_path || ""; onClicked: vmYamlEditor.copyPath(treeList.currentIndex) }
                                HusButton { Layout.fillWidth: true; text: opsLoc.copy_value || ""; onClicked: vmYamlEditor.copyValue(treeList.currentIndex) }
                                HusButton { Layout.fillWidth: true; text: opsLoc["delete"] || ""; onClicked: confirmDelete() }
                                HusButton { Layout.fillWidth: true; text: opsLoc.range_delete || ""; onClicked: rangeDialog.openDialog() }
                            }
                        }
                    }

                    HusText {
                        text: vmYamlEditor.pinnedText
                        color: HusTheme.Primary.colorTextTertiary
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Item { Layout.fillHeight: true }
                }
            }
        }

        // 源码视图
        GlassPanel {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: vmYamlEditor.viewMode !== 0

            LockedFlickable {
                id: sourceFlick
                anchors.fill: parent
                anchors.margins: 4
                contentWidth: width
                contentHeight: sourceEdit.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: HusScrollBar { }

                TextArea.flickable: TextArea {
                    id: sourceEdit
                    width: sourceFlick.width
                    font.family: "Consolas"
                    font.pixelSize: 13
                    color: HusTheme.Primary.colorTextBase
                    selectionColor: HusTheme.Primary.colorPrimary
                    wrapMode: TextEdit.NoWrap
                    text: vmYamlEditor.sourceText

                    Component.onCompleted: vmYamlEditor.attachSourceHighlighter(textDocument)

                    onTextChanged: sourceTimer.restart()
                }
            }

            Timer {
                id: sourceTimer
                interval: 500
                onTriggered: vmYamlEditor.applySourceText(sourceEdit.text)
            }
        }
    }

    // ---- 状态栏 ----
    RowLayout {
        Layout.fillWidth: true
        spacing: 14
        visible: vmYamlEditor.saveLoaded
        HusText {
            text: "● " + vmYamlEditor.statusValidText
            color: vmYamlEditor.sourceValid ? "#97C459" : "#F09595"
        }
        HusText { text: vmYamlEditor.statusNodesText; color: HusTheme.Primary.colorTextSecondary }
        HusText {
            text: vmYamlEditor.statusModifiedText
            color: appBridge.dirty ? "#EF9F27" : HusTheme.Primary.colorTextTertiary
        }
        Item { Layout.fillWidth: true }
        HusText {
            text: (loc.shortcuts || ({})).hint || ""
            color: HusTheme.Primary.colorTextTertiary
            font.pixelSize: 11
        }
    }

    function confirmDelete() {
        var count = vmYamlEditor.deleteSelectionCount();
        if (count <= 0) return;
        if (count === 1) { vmYamlEditor.deleteSelection(); return; }
        deleteConfirmDialog.count = count;
        deleteConfirmDialog.open();
    }

    // ---- 右键菜单 ----
    HusModal {
        id: contextMenu
        width: 240
        closable: true
        property int row: -1
        function openFor(row) {
            contextMenu.row = row;
            title = "";
            open();
        }
        contentDelegate: Item {
            implicitHeight: ctxColumn.implicitHeight
            ColumnLayout {
                id: ctxColumn
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: 2
                HusButton { Layout.fillWidth: true; text: opsLoc.add_child || ""; onClicked: { addChildDialog.open(); contextMenu.close(); } }
                HusButton { Layout.fillWidth: true; text: opsLoc.rename || ""; onClicked: { renameDialog.open(); contextMenu.close(); } }
                HusButton { Layout.fillWidth: true; text: opsLoc.duplicate || ""; onClicked: { vmYamlEditor.duplicateRow(contextMenu.row); contextMenu.close(); } }
                HusButton { Layout.fillWidth: true; text: opsLoc.copy_path || ""; onClicked: { vmYamlEditor.copyPath(contextMenu.row); contextMenu.close(); } }
                HusButton { Layout.fillWidth: true; text: opsLoc.copy_value || ""; onClicked: { vmYamlEditor.copyValue(contextMenu.row); contextMenu.close(); } }
                HusButton { Layout.fillWidth: true; text: opsLoc["delete"] || ""; onClicked: { page.confirmDelete(); contextMenu.close(); } }
                HusButton { Layout.fillWidth: true; text: opsLoc.range_delete || ""; onClicked: { rangeDialog.openDialog(); contextMenu.close(); } }
            }
        }
    }

    // ---- 添加子节点 ----
    // 只替换 bodyDelegate（contentDelegate 会连确定/取消按钮一起丢掉）；委托内的 id
    // 在 onConfirm 里取不到，输入值放在 dialog 上
    HusModal {
        id: addChildDialog
        objectName: "addChildDialog"
        property string childKey: ""
        property int typeIndex: 0
        readonly property var typeOptions: {
            var t = (page.loc.types || ({}));
            return ["str", "int", "float", "bool", "null", "dict", "list"].map(function(k) {
                return { key: k, label: t[k] || k };
            });
        }
        width: 380
        closable: true
        title: (loc.dialogs || ({})).add_child_title || ""
        confirmText: (loc.dialogs || ({})).confirm || "OK"
        cancelText: (loc.dialogs || ({})).cancel || "Cancel"
        onAboutToShow: { childKey = ""; typeIndex = 0; }
        onConfirm: {
            close();
            vmYamlEditor.addChild(treeList.currentIndex, childKey, typeOptions[typeIndex].key);
        }
        onCancel: close()
        bodyDelegate: Column {
            spacing: 10
            HusText { text: (loc.dialogs || ({})).child_key || ""; color: HusTheme.Primary.colorTextSecondary }
            HusInput {
                id: childKeyInput
                width: parent.width
                onTextChanged: addChildDialog.childKey = text
                Connections {
                    target: addChildDialog
                    function onAboutToShow() { childKeyInput.text = ""; }
                    function onOpened() { childKeyInput.forceActiveFocus(); }
                }
            }
            HusText { text: (loc.dialogs || ({})).child_type || ""; color: HusTheme.Primary.colorTextSecondary }
            AppSelect {
                width: parent.width
                model: addChildDialog.typeOptions
                textRole: "label"
                currentIndex: addChildDialog.typeIndex
                onActivated: function(index) { addChildDialog.typeIndex = index; }
            }
        }
    }

    // ---- 重命名 ----
    HusModal {
        id: renameDialog
        objectName: "renameDialog"
        property string newName: ""
        width: 380
        closable: true
        title: opsLoc.rename || ""
        confirmText: (loc.dialogs || ({})).confirm || "OK"
        cancelText: (loc.dialogs || ({})).cancel || "Cancel"
        onAboutToShow: {
            var row = vmYamlEditor.rows[treeList.currentIndex];
            newName = row ? String(row.key) : "";
        }
        onConfirm: { close(); vmYamlEditor.renameKey(treeList.currentIndex, newName); }
        onCancel: close()
        bodyDelegate: HusInput {
            id: renameField
            width: parent ? parent.width : 0
            onTextChanged: renameDialog.newName = text
            Keys.onReturnPressed: renameDialog.confirm()
            Keys.onEnterPressed: renameDialog.confirm()
            Connections {
                target: renameDialog
                function onOpened() { renameField.text = renameDialog.newName; renameField.forceActiveFocus(); renameField.selectAll(); }
            }
        }
    }

    // ---- 删除确认 ----
    HusModal {
        id: deleteConfirmDialog
        width: 380
        closable: true
        property int count: 0
        title: opsLoc["delete"] || ""
        description: ((loc.dialogs || ({})).delete_confirm || "").replace("{count}", count)
        confirmText: opsLoc["delete"] || ""
        cancelText: (loc.dialogs || ({})).cancel || "Cancel"
        onConfirm: { vmYamlEditor.deleteSelection(); close(); }
        onCancel: close()
    }

    // ---- 范围删除 ----
    HusModal {
        id: rangeDialog
        width: 420
        closable: true
        title: (loc.dialogs || ({})).range_delete_title || ""

        property int minSlot: 0
        property int maxSlot: 0

        function openDialog() {
            var info = vmYamlEditor.rangeDeleteInfo();
            if (!info.min && info.min !== 0) {
                appBridge.toast((page.loc.dialogs || ({})).range_none || "", "warning");
                return;
            }
            minSlot = info.min;
            maxSlot = info.max;
            fromInput.value = minSlot;
            toInput.value = maxSlot;
            open();
        }

        contentDelegate: Item {
            implicitHeight: rangeColumn.implicitHeight
            ColumnLayout {
                id: rangeColumn
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: 10
                RowLayout {
                    spacing: 10
                    HusText { text: (page.loc.dialogs || ({})).range_from || ""; color: HusTheme.Primary.colorTextSecondary }
                    HusInputInteger {
                        id: fromInput
                        Layout.fillWidth: true
                        min: rangeDialog.minSlot
                        max: rangeDialog.maxSlot
                    }
                    HusText { text: (page.loc.dialogs || ({})).range_to || ""; color: HusTheme.Primary.colorTextSecondary }
                    HusInputInteger {
                        id: toInput
                        Layout.fillWidth: true
                        min: rangeDialog.minSlot
                        max: rangeDialog.maxSlot
                    }
                }
                HusText {
                    text: {
                        var a = Math.min(fromInput.value, toInput.value);
                        var b = Math.max(fromInput.value, toInput.value);
                        var count = vmYamlEditor.rangeDeleteCount(a, b);
                        var tpl = (page.loc.dialogs || ({})).range_preview || "";
                        return tpl.replace("{count}", count).replace("{from}", a).replace("{to}", b);
                    }
                    color: "#EF9F27"
                }
                RowLayout {
                    spacing: 8
                    Item { Layout.fillWidth: true }
                    HusButton {
                        text: (page.loc.dialogs || ({})).range_confirm || ""
                        type: HusButton.Type_Primary
                        enabled: vmYamlEditor.rangeDeleteCount(Math.min(fromInput.value, toInput.value), Math.max(fromInput.value, toInput.value)) > 0
                        onClicked: {
                            vmYamlEditor.rangeDelete(Math.min(fromInput.value, toInput.value), Math.max(fromInput.value, toInput.value));
                            rangeDialog.close();
                        }
                    }
                    HusButton {
                        text: (page.loc.dialogs || ({})).cancel || "Cancel"
                        onClicked: rangeDialog.close()
                    }
                }
            }
        }
    }
}
