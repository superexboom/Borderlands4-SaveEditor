// 装备编辑器共享页面：对齐主线 BaseEquipmentEditorTab 的布局
// 使用方式：GrenadePage.qml 等薄包装页设置 vm 属性
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic

LockedFlickable {
    id: page
    contentWidth: width
    contentHeight: column.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: HusScrollBar { }

    property var vm: null
    readonly property var loc: vm ? vm.strings : ({})
    readonly property var groupsLoc: loc.groups || ({})
    readonly property var labelsLoc: loc.labels || ({})
    readonly property var dialogsLoc: loc.dialogs || ({})

    SelectionStyle { id: pageSelStyle }

    ColumnLayout {
        id: column
        width: page.width - 2
        spacing: 10

        EmptyHint {
            Layout.fillWidth: true
            Layout.preferredHeight: 160
            visible: vm && !vm.dataLoaded
            description: vm ? vm.loadErrorText : ""
        }

        // ---- 来源条 ----
        RowLayout {
            Layout.fillWidth: true
            visible: vm && vm.dataLoaded
            spacing: 8
            HusText {
                text: vm ? vm.sourceText : ""
                color: HusTheme.Primary.colorTextSecondary
                elide: Text.ElideMiddle
                Layout.fillWidth: true
            }
            HusIconButton {
                text: vm && vm.sourceTexts ? vm.sourceTexts.backpack : ""
                iconSource: HusIcon.InboxOutlined
                onClicked: {
                    if (vm.prepareBackpackImport() > 0)
                        backpackDialog.open();
                }
            }
            HusIconButton {
                text: vm && vm.sourceTexts ? vm.sourceTexts.base85 : ""
                iconSource: HusIcon.LinkOutlined
                onClicked: base85Dialog.open()
            }
            HusIconButton {
                text: vm && vm.sourceTexts ? vm.sourceTexts.reset : ""
                iconSource: HusIcon.ReloadOutlined
                onClicked: vm.resetSource()
            }
        }

        // ---- 输出组 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: outputColumn.implicitHeight + 28
            visible: vm && vm.dataLoaded

            ColumnLayout {
                id: outputColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                spacing: 8
                HusText { text: groupsLoc.output || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                RowLayout {
                    spacing: 8
                    HusText { Layout.preferredWidth: 86; text: labelsLoc.deserialize || "Deserialize:"; color: HusTheme.Primary.colorTextSecondary }
                    HusInput {
                        Layout.fillWidth: true
                        readOnly: true
                        text: vm ? vm.rawOutput : ""
                    }
                    HusIconButton {
                        iconSource: HusIcon.CopyOutlined
                        contentDescription: dialogsLoc.copy || "Copy"
                        onClicked: vm.copyRawToClipboard()
                    }
                }
                RowLayout {
                    spacing: 8
                    HusText { Layout.preferredWidth: 86; text: labelsLoc.base85 || "Base85:"; color: HusTheme.Primary.colorTextSecondary }
                    HusInput {
                        Layout.fillWidth: true
                        readOnly: true
                        text: vm ? vm.base85Output : ""
                        color: vm && vm.encodeError ? HusTheme.Primary.colorError : HusTheme.Primary.colorTextBase
                    }
                    HusIconButton {
                        iconSource: HusIcon.CopyOutlined
                        contentDescription: dialogsLoc.copy || "Copy"
                        onClicked: vm.copyBase85ToClipboard()
                    }
                    AppSelect {
                        Layout.preferredWidth: 150
                        model: vm ? vm.flagOptions : []
                        currentIndex: vm ? vm.flagIndex : 0
                        onActivated: function(index) { vm.setFlagIndex(index); }
                    }
                    HusIconButton {
                        text: labelsLoc.add_to_backpack || ""
                        type: HusButton.Type_Primary
                        iconSource: HusIcon.PlusOutlined
                        enabled: vm && !vm.encodeError && appBridge.saveLoaded
                        onClicked: vm.addToBackpack()
                    }
                }
            }
        }

        // ---- 顶部控制 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: topRow.implicitHeight + 28
            visible: vm && vm.dataLoaded

            RowLayout {
                id: topRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                spacing: 10
                HusText { text: labelsLoc.manufacturer || ""; color: HusTheme.Primary.colorTextSecondary }
                AppSelect {
                    Layout.fillWidth: true
                    model: vm ? vm.mfgOptions : []
                    currentIndex: vm ? vm.mfgIndex : 0
                    enabled: vm && !vm.importedCopy
                    onActivated: function(index) { vm.setMfgIndex(index); }
                }
                HusText { text: labelsLoc.level || ""; color: HusTheme.Primary.colorTextSecondary }
                HusInput {
                    Layout.preferredWidth: 80
                    text: vm ? vm.level : ""
                    validator: IntValidator { bottom: 1; top: 999 }
                    onEditingFinished: vm.setLevel(text)
                }
                HusText { text: labelsLoc.rarity || ""; color: HusTheme.Primary.colorTextSecondary }
                AppSelect {
                    Layout.fillWidth: true
                    model: vm ? vm.rarityOptions : []
                    currentIndex: vm ? vm.rarityIndex : -1
                    onActivated: function(index) { vm.setRarityIndex(index); }
                }
                // 幸运 Roll（对齐主线 MenuButtonPopup）：主按钮=按上次约束快速 roll；
                // 箭头=向下展开约束面板（厂商/类型/稀有度/指定装备/数量 + 匹配数 + Roll）
                RowLayout {
                    spacing: 4
                    HusIconButton {
                        text: "🎲 " + (vm && vm.rollTexts ? vm.rollTexts.lucky : "")
                        contentDescription: vm && vm.rollTexts ? vm.rollTexts.roll_scope_tip || "" : ""
                        onClicked: {
                            if (vm.quickRoll())
                                rollDialog.openResults();
                        }
                    }
                    HusIconButton {
                        id: luckyArrow
                        iconSource: HusIcon.DownOutlined
                        contentDescription: vm && vm.rollTexts ? vm.rollTexts.constraints_title : ""
                        onClicked: rollPopup.opened ? rollPopup.close() : rollPopup.openFor()

                        HusPopup {
                            id: rollPopup
                            y: luckyArrow.height + 4
                            x: luckyArrow.width - width
                            width: 400
                            padding: 12
                            modal: false
                            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

                            property var constraintOptions: null

                            function indexOfValue(select, value) {
                                if (value === undefined || value === null) return 0;
                                for (var i = 0; i < select.model.length; i++)
                                    if (select.model[i].value === value) return i;
                                return 0;
                            }

                            function openFor() {
                                constraintOptions = vm.rollConstraintOptions();
                                var saved = vm.rollConstraints || ({});
                                open();
                                // 弹层关闭期间内容不可见，visible 绑定延迟不求值，行的显隐须在
                                // 打开时命令式同步（类型行仅当目录有多个类型，对齐主线 show_weapon_type）
                                rollTypeRow.visible = !!(constraintOptions && constraintOptions.show_type);
                                rollNamedRow.visible = !!(constraintOptions && constraintOptions.named_items.length > 1);
                                rollMfgSel.currentIndex = indexOfValue(rollMfgSel, saved.manufacturer);
                                rollTypeSel.currentIndex = indexOfValue(rollTypeSel, saved.weapon_type);
                                rollRaritySel.currentIndex = indexOfValue(rollRaritySel, saved.rarity);
                                rollNamedSel.currentIndex = indexOfValue(rollNamedSel, saved.composition_ref);
                                rollCountInput.value = Math.max(1, Math.min(50, vm.rollCount));
                                syncNamedLock();
                                refreshMatch();
                            }

                            function currentConstraints() {
                                return {
                                    manufacturer: rollMfgSel.model[rollMfgSel.currentIndex].value,
                                    weapon_type: rollTypeRow.visible
                                                 ? rollTypeSel.model[rollTypeSel.currentIndex].value : null,
                                    rarity: rollRaritySel.model[rollRaritySel.currentIndex].value,
                                    composition_ref: rollNamedRow.visible && rollNamedSel.currentIndex > 0
                                                     ? rollNamedSel.model[rollNamedSel.currentIndex].value : null,
                                };
                            }

                            // 对齐主线 _on_named_changed：选中指定装备后联动锁定其余约束
                            function syncNamedLock() {
                                var named = rollNamedRow.visible && rollNamedSel.currentIndex > 0
                                          ? rollNamedSel.model[rollNamedSel.currentIndex] : null;
                                if (named) {
                                    rollMfgSel.currentIndex = indexOfValue(rollMfgSel, named.manufacturer);
                                    rollTypeSel.currentIndex = indexOfValue(rollTypeSel, named.weapon_type);
                                    rollRaritySel.currentIndex = indexOfValue(rollRaritySel, named.rarity);
                                }
                                rollMfgSel.enabled = !named;
                                rollTypeSel.enabled = !named;
                                rollRaritySel.enabled = !named;
                            }

                            function refreshMatch() {
                                var n = vm.rollMatchCount(currentConstraints());
                                rollMatchText.text = n > 0
                                        ? (vm.rollTexts.matches || "Matches: {count}").replace("{count}", n)
                                        : (vm.rollTexts.no_matches || "No matches");
                                rollNowButton.enabled = n > 0;
                            }

                            contentItem: ColumnLayout {
                                spacing: 8
                                HusText {
                                    text: vm && vm.rollTexts ? vm.rollTexts.constraints_title : ""
                                    font.bold: true
                                    color: HusTheme.Primary.colorTextBase
                                }
                                RowLayout {
                                    spacing: 8
                                    HusText { Layout.preferredWidth: 64; text: vm.rollTexts.manufacturer; color: HusTheme.Primary.colorTextSecondary }
                                    AppSelect {
                                        id: rollMfgSel
                                        Layout.fillWidth: true
                                        model: rollPopup.constraintOptions ? rollPopup.constraintOptions.manufacturers : []
                                        onActivated: rollPopup.refreshMatch()
                                    }
                                }
                                RowLayout {
                                    id: rollTypeRow
                                    spacing: 8
                                    HusText { Layout.preferredWidth: 64; text: vm.rollTexts.weapon_type; color: HusTheme.Primary.colorTextSecondary }
                                    AppSelect {
                                        id: rollTypeSel
                                        Layout.fillWidth: true
                                        model: rollPopup.constraintOptions ? rollPopup.constraintOptions.weapon_types : []
                                        onActivated: rollPopup.refreshMatch()
                                    }
                                }
                                RowLayout {
                                    spacing: 8
                                    HusText { Layout.preferredWidth: 64; text: vm.rollTexts.rarity; color: HusTheme.Primary.colorTextSecondary }
                                    AppSelect {
                                        id: rollRaritySel
                                        Layout.fillWidth: true
                                        model: rollPopup.constraintOptions ? rollPopup.constraintOptions.rarities : []
                                        onActivated: rollPopup.refreshMatch()
                                    }
                                }
                                RowLayout {
                                    id: rollNamedRow
                                    spacing: 8
                                    HusText { Layout.preferredWidth: 64; text: vm.rollTexts.named_item; color: HusTheme.Primary.colorTextSecondary }
                                    AppSelect {
                                        id: rollNamedSel
                                        Layout.fillWidth: true
                                        model: rollPopup.constraintOptions ? rollPopup.constraintOptions.named_items : []
                                        onActivated: { rollPopup.syncNamedLock(); rollPopup.refreshMatch(); }
                                    }
                                }
                                RowLayout {
                                    spacing: 8
                                    HusText { Layout.preferredWidth: 64; text: vm.rollTexts.count; color: HusTheme.Primary.colorTextSecondary }
                                    HusInputInteger {
                                        id: rollCountInput
                                        min: 1
                                        max: 50
                                        value: 5
                                        Layout.preferredWidth: 110
                                    }
                                    HusText {
                                        id: rollMatchText
                                        Layout.fillWidth: true
                                        color: HusTheme.Primary.colorTextSecondary
                                        font.pixelSize: 12
                                    }
                                }
                                HusButton {
                                    id: rollNowButton
                                    Layout.fillWidth: true
                                    text: vm.rollTexts.roll
                                    type: HusButton.Type_Primary
                                    onClicked: {
                                        if (vm.roll(rollPopup.currentConstraints(), rollCountInput.value)) {
                                            rollPopup.close();
                                            rollDialog.openResults();
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // ---- 属性预览 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: statsColumn.implicitHeight + 28
            visible: vm && vm.dataLoaded

            ColumnLayout {
                id: statsColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                spacing: 6
                HusText { text: groupsLoc.base_attrs || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 4
                    columnSpacing: 16
                    rowSpacing: 4
                    Repeater {
                        model: vm ? vm.statsPreview : []
                        delegate: RowLayout {
                            spacing: 6
                            HusText {
                                text: modelData.label
                                color: HusTheme.Primary.colorTextSecondary
                                font.pixelSize: 12
                            }
                            HusText {
                                text: modelData.value
                                color: HusTheme.Primary.colorTextBase
                                font.pixelSize: 12
                                font.bold: true
                            }
                        }
                    }
                }
                HusText {
                    visible: !vm || vm.statsPreview.length === 0
                    text: labelsLoc.no_stats || "—"
                    color: HusTheme.Primary.colorTextTertiary
                    font.pixelSize: 12
                }
            }
        }

        // ---- 合法性指引 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: guideRow.implicitHeight + 24
            visible: vm && vm.dataLoaded && vm.guidance && vm.guidance.status !== ""

            RowLayout {
                id: guideRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 12
                spacing: 10
                HusTag {
                    text: vm ? vm.guidance.status : ""
                    presetColor: vm && vm.guidance.statusKey === "legal" ? "green"
                               : vm && vm.guidance.statusKey === "unknown" ? "default" : "orange"
                }
                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true
                    HusText {
                        text: vm ? vm.guidance.reason : ""
                        color: HusTheme.Primary.colorTextBase
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                        font.pixelSize: 12
                    }
                    HusText {
                        visible: text !== ""
                        text: vm ? vm.guidance.groups : ""
                        color: HusTheme.Primary.colorTextSecondary
                        font.pixelSize: 11
                    }
                }
            }
        }

        // ---- perk 组 ----
        Repeater {
            model: vm && vm.dataLoaded ? vm.groups : []
            delegate: GlassPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: groupColumn.implicitHeight + 28

                property var group: modelData

                ColumnLayout {
                    id: groupColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    spacing: 8
                    HusText {
                        visible: group.mode !== "picker"
                        text: group.title
                        font.bold: true
                        color: HusTheme.Primary.colorTextBase
                    }

                    // chip 组：单选下拉（主线 OptionCombo）
                    AppSelect {
                        visible: group.mode === "chip"
                        Layout.fillWidth: true
                        model: group.mode === "chip" ? group.options : []
                        displayText: {
                            if (group.mode !== "chip") return "";
                            var sel = null;
                            for (var i = 0; i < group.options.length; i++)
                                if (group.options[i].selected) { sel = group.options[i]; break; }
                            if (!sel) sel = group.options.length ? group.options[0] : null;
                            // label 已含 legit marker 前缀（HusSelect 弹层只渲染 label）
                            return sel ? sel.label : "";
                        }
                        onActivated: function(index) { vm.selectChip(group.key, model[index].pid); }
                    }

                    // picker 组：内嵌双栏目录面板（对齐主线 CatalogPicker；
                    // 面板自绘组标题含预算后缀，故上方组标题仅 chip 模式显示）
                    CatalogPickerPanel {
                        visible: group.mode === "picker"
                        Layout.fillWidth: true
                        title: group.title
                        options: group.mode === "picker" ? group.options : []
                        categories: group.mode === "picker" ? group.categories : []
                        entries: group.mode === "picker" ? group.entries : []
                        stackable: !!group.stackable
                        clearText: (loc.buttons && loc.buttons.clear) || "Clear"
                        addText: (loc.buttons && loc.buttons.add_selected)
                                 || (appBridge.language === "zh-CN" ? "添加所选 →" : "Add selected →")
                        availText: (loc.misc && loc.misc.available)
                                   || (appBridge.language === "zh-CN" ? "可选" : "Available")
                        selectedText: (loc.misc && loc.misc.selected)
                                      || (appBridge.language === "zh-CN" ? "已选" : "Selected")
                        onAddRequested: function(keys) { vm.addPickerItems(group.key, keys); }
                        onRemoveRequested: function(index) { vm.removePickerItem(group.key, index); }
                        onCountChanged: function(indices, value) { vm.setPickerItemsCount(group.key, indices, value); }
                        onCountStepped: function(indices, delta) { vm.stepPickerItemsCount(group.key, indices, delta); }
                        onClearRequested: vm.clearPickerGroup(group.key)
                    }
                }
            }
        }

        Item { Layout.preferredHeight: 6 }
    }

    // ---- 背包导入对话框 ----
    BackpackImportDialog { id: backpackDialog; vm: page.vm }

    // ---- Base85 导入对话框 ----
    HusModal {
        id: base85Dialog
        width: 560
        closable: true
        title: vm && vm.sourceTexts ? vm.sourceTexts.base85 : ""
        confirmText: appBridge.trFormat("main_window.dialogs.confirm", {default: "OK"})
        cancelText: appBridge.trText("main_window.dialogs.cancel")
        onConfirm: { vm.importBase85(base85Input.text); close(); }
        onCancel: close()

        contentDelegate: Item {
            implicitHeight: 90
            ColumnLayout {
                anchors.fill: parent
                HusInput {
                    id: base85Input
                    Layout.fillWidth: true
                    placeholderText: "@U..."
                }
            }
        }
    }

    // ---- Roll 结果对话框（约束编辑在幸运按钮箭头的 rollPopup 里） ----
    HusModal {
        id: rollDialog
        width: 900
        height: 640
        closable: true
        // 弹窗底色：不用套件默认的暗浊色，用与玻璃面板一致的清爽深色/浅色
        colorBg: HusTheme.isDark ? "#1f242d" : "#f7f8fa"

        property bool hasResults: false

        function openResults() {
            title = vm.rollTexts.results_title;
            hasResults = true;
            open();
        }

        contentDelegate: Item {
            // 高度拉满弹窗（消除底部空白），四周留白（自定义 contentDelegate 不带内边距）
            implicitHeight: rollDialog.height - 4
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 10
                RowLayout {
                    HusText {
                        Layout.fillWidth: true
                        text: rollDialog.title
                        font.bold: true
                        font.pixelSize: 15
                        color: HusTheme.Primary.colorTextBase
                        elide: Text.ElideRight
                    }
                    HusIconButton {
                        iconSource: HusIcon.CloseOutlined
                        onClicked: rollDialog.close()
                    }
                }
                HusText {
                    visible: rollDialog.hasResults
                    text: vm.rollSummaryText
                    color: HusTheme.Primary.colorTextSecondary
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
                RollResultsView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: rollDialog.hasResults
                    results: rollDialog.hasResults ? vm.rollResults : []
                    texts: vm.rollTexts
                    canAdd: appBridge.saveLoaded
                    onAddRequested: function(indices) { vm.addRollToBackpack(indices); }
                    onCopyRequested: function(index) { vm.copyRollResult(index); }
                }
                RowLayout {
                    visible: rollDialog.hasResults
                    spacing: 8
                    Item { Layout.fillWidth: true }
                    HusButton {
                        text: vm.rollTexts.add_all
                        type: HusButton.Type_Primary
                        enabled: appBridge.saveLoaded
                        onClicked: {
                            var indices = [];
                            for (var i = 0; i < vm.rollResults.length; i++) indices.push(i);
                            vm.addRollToBackpack(indices);
                        }
                    }
                }
            }
        }
    }
}
