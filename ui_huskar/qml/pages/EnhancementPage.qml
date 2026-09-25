import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "../components"

// 强化模组编辑器页：对齐主线 QtEnhancementEditorTab
LockedFlickable {
    id: page
    objectName: "enhancementPage"
    enabled: !vmEnhancement.rollBusy
    contentWidth: width
    contentHeight: column.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: HusScrollBar { }

    readonly property var vmLoc: vmEnhancement.strings
    readonly property var groupsLoc: vmLoc.groups || ({})
    readonly property var labelsLoc: vmLoc.labels || ({})
    readonly property var dialogsLoc: vmLoc.dialogs || ({})

    SelectionStyle { id: selStyle }

    Connections {
        target: vmEnhancement
        function onRollFinished(ok) {
            if (ok) enhancementRollDialog.openResults()
        }
    }

    ColumnLayout {
        id: column
        width: page.width - 2
        spacing: 10

        EmptyHint {
            Layout.fillWidth: true
            Layout.preferredHeight: 160
            visible: !vmEnhancement.dataLoaded
            description: vmEnhancement.loadErrorText
        }

        // ---- 来源条 ----
        RowLayout {
            Layout.fillWidth: true
            visible: vmEnhancement.dataLoaded
            spacing: 8
            HusText {
                text: vmEnhancement.sourceText
                color: HusTheme.Primary.colorTextSecondary
                elide: Text.ElideMiddle
                Layout.fillWidth: true
            }
            HusIconButton {
                text: vmEnhancement.sourceTexts.backpack || ""
                iconSource: HusIcon.InboxOutlined
                onClicked: { if (vmEnhancement.prepareBackpackImport() > 0) backpackDialog.open(); }
            }
            HusIconButton {
                text: vmEnhancement.sourceTexts.base85 || ""
                iconSource: HusIcon.LinkOutlined
                onClicked: base85Dialog.open()
            }
            HusIconButton {
                text: vmEnhancement.sourceTexts.reset || ""
                iconSource: HusIcon.ReloadOutlined
                onClicked: vmEnhancement.resetSource()
            }
        }

        // ---- 输出 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: outputColumn.implicitHeight + 28
            visible: vmEnhancement.dataLoaded

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
                    HusInput {
                        Layout.fillWidth: true
                        readOnly: true
                        text: vmEnhancement.rawOutput
                    }
                    HusIconButton {
                        iconSource: HusIcon.CopyOutlined
                        onClicked: vmEnhancement.copyRawToClipboard()
                    }
                }
                HusText { text: groupsLoc.base85 || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                RowLayout {
                    spacing: 8
                    HusInput {
                        Layout.fillWidth: true
                        readOnly: true
                        text: vmEnhancement.base85Output
                        color: vmEnhancement.encodeError ? HusTheme.Primary.colorError : HusTheme.Primary.colorTextBase
                    }
                    HusIconButton {
                        iconSource: HusIcon.CopyOutlined
                        onClicked: vmEnhancement.copyBase85ToClipboard()
                    }
                    AppSelect {
                        Layout.preferredWidth: 150
                        model: vmEnhancement.flagOptions
                        currentIndex: vmEnhancement.flagIndex
                        onActivated: function(index) { vmEnhancement.setFlagIndex(index); }
                    }
                    HusIconButton {
                        text: (vmLoc.buttons || ({})).add_to_backpack || ""
                        type: HusButton.Type_Primary
                        iconSource: HusIcon.PlusOutlined
                        enabled: !vmEnhancement.encodeError && appBridge.saveLoaded
                        onClicked: vmEnhancement.addToBackpack()
                    }
                }
            }
        }

        // ---- 厂商 / 稀有度 / 等级 ----
        RowLayout {
            Layout.fillWidth: true
            visible: vmEnhancement.dataLoaded
            spacing: 10
            HusText { text: labelsLoc.manufacturer || ""; color: HusTheme.Primary.colorTextSecondary }
            AppSelect {
                Layout.fillWidth: true
                model: vmEnhancement.mfgOptions
                currentIndex: vmEnhancement.mfgIndex
                enabled: !vmEnhancement.importedCopy
                onActivated: function(index) { vmEnhancement.setMfgIndex(index); }
            }
            HusText { text: labelsLoc.rarity || ""; color: HusTheme.Primary.colorTextSecondary }
            AppSelect {
                Layout.fillWidth: true
                model: vmEnhancement.rarityOptions
                currentIndex: vmEnhancement.rarityIndex
                onActivated: function(index) { vmEnhancement.setRarityIndex(index); }
            }
            HusText { text: labelsLoc.level || ""; color: HusTheme.Primary.colorTextSecondary }
            HusInput {
                Layout.preferredWidth: 80
                text: vmEnhancement.level
                validator: IntValidator { bottom: 1; top: 999 }
                onEditingFinished: vmEnhancement.setLevel(text)
            }
        }

        // ---- Legit 构筑状态（独立详情盒，紧跟厂商控制） ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: enhancementLegitRow.implicitHeight + 24
            visible: vmEnhancement.dataLoaded

            RowLayout {
                id: enhancementLegitRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 12
                spacing: 12
                LegitIndicator {
                    objectName: "enhancementLegitIndicator"
                    status: vmEnhancement.legitBadge.status
                    label: vmEnhancement.legitBadge.label
                    detail: vmEnhancement.legitBadge.detail
                }
                HusText {
                    Layout.fillWidth: true
                    text: vmEnhancement.legitBadge.detail || ""
                    color: HusTheme.Primary.colorTextSecondary
                    wrapMode: Text.Wrap
                    textFormat: Text.PlainText
                }
                RowLayout {
                    spacing: 4
                    HusButton {
                        objectName: "enhancementLuckyRoll"
                        text: "🎲 " + (vmEnhancement.rollBusy
                              ? (vmEnhancement.rollTexts.rolling || "生成中…")
                              : (vmEnhancement.rollTexts.lucky || ""))
                        enabled: vmEnhancement.dataLoaded && !vmEnhancement.rollBusy
                        onClicked: vmEnhancement.startQuickRoll()
                    }
                    HusIconButton {
                        id: enhancementLuckyArrow
                        objectName: "enhancementLuckyArrow"
                        iconSource: HusIcon.DownOutlined
                        contentDescription: vmEnhancement.rollTexts.constraints_title || ""
                        onClicked: enhancementRollPopup.opened ? enhancementRollPopup.close() : enhancementRollPopup.openFor()
                    }
                }
            }
        }

        // ---- perk 复选 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: perksColumn.implicitHeight + 28
            visible: vmEnhancement.dataLoaded

            ColumnLayout {
                id: perksColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                spacing: 6
                HusText {
                    text: (groupsLoc.perks_mfg || "") + " · " + vmEnhancement.coreGuidance
                    font.bold: true
                    color: HusTheme.Primary.colorTextBase
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        model: vmEnhancement.perkChecks
                        delegate: LegitChip {
                            text: (modelData.marker ? modelData.marker + "  " : "") + modelData.label
                            fullText: [modelData.hint, modelData.detail].filter(function(x) { return x; }).join("<br><br>")
                            checked: modelData.checked
                            kind: modelData.kind
                            onClicked: vmEnhancement.setPerkChecked(modelData.index, !modelData.checked)
                        }
                    }
                }
            }
        }

        // ---- 堆叠 picker ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: stackPanel.implicitHeight + 28
            visible: vmEnhancement.dataLoaded

            CatalogPickerPanel {
                id: stackPanel
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                title: (groupsLoc.perk_stacking || "") + " · " + vmEnhancement.stackGuidance
                options: vmEnhancement.stackOptions
                categories: vmEnhancement.stackCategories
                entries: vmEnhancement.stackEntries
                stackable: false
                clearText: (vmLoc.buttons || ({})).clear || "Clear"
                addText: (vmLoc.buttons || ({})).add_selected || ((appBridge.language === "zh-CN") ? "添加所选 →" : "Add selected →")
                availText: (vmLoc.picker || ({})).available || ((appBridge.language === "zh-CN") ? "可选" : "Available")
                selectedText: (vmLoc.picker || ({})).selected_stacks || ((appBridge.language === "zh-CN") ? "已选专长" : "Selected Stacks")
                onAddRequested: function(keys) { vmEnhancement.addStackItems(keys); }
                onRemoveRequested: function(index) { vmEnhancement.removeStackItem(index); }
                onClearRequested: vmEnhancement.clearStack()
            }
        }

        // ---- 247 stats picker ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: statPanel.implicitHeight + 28
            visible: vmEnhancement.dataLoaded

            CatalogPickerPanel {
                id: statPanel
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                title: (groupsLoc.builder_247 || "") + " · " + vmEnhancement.statGuidance
                options: vmEnhancement.statOptions
                categories: vmEnhancement.statCategories
                subcategories: vmEnhancement.statSubcategories
                entries: vmEnhancement.statEntries
                listHeight: 720
                clearText: (vmLoc.buttons || ({})).clear || "Clear"
                addText: (vmLoc.buttons || ({})).add_selected || ((appBridge.language === "zh-CN") ? "添加所选 →" : "Add selected →")
                availText: (vmLoc.picker || ({})).available || ((appBridge.language === "zh-CN") ? "可选" : "Available")
                selectedText: (vmLoc.picker || ({})).selected_stats || ((appBridge.language === "zh-CN") ? "已选属性" : "Selected Stats")
                onAddRequested: function(keys) { vmEnhancement.addStatItems(keys); }
                onRemoveRequested: function(index) { vmEnhancement.removeStatItem(index); }
                onCountChanged: function(indices, value) { vmEnhancement.setStatItemsCount(indices, value); }
                onCountStepped: function(indices, delta) { vmEnhancement.stepStatItemsCount(indices, delta); }
                onClearRequested: vmEnhancement.clearStat()
            }
        }

        // ---- Special Thanks ----
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: thanksText.implicitHeight + 20
            visible: (vmEnhancement.specialThanks.content || "") !== ""
            color: "#14009688"
            border.color: "#4D009688"
            radius: 6
            HusText {
                id: thanksText
                anchors.fill: parent
                anchors.margins: 10
                wrapMode: Text.Wrap
                color: "#4dd0c8"
                textFormat: Text.RichText
                text: "<b>✨ " + (vmEnhancement.specialThanks.title || "") + "</b><br>"
                      + (vmEnhancement.specialThanks.content || "").replace(/\n/g, "<br>")
            }
        }

        Item { Layout.preferredHeight: 6 }
    }

    BackpackImportDialog { id: backpackDialog; vm: vmEnhancement }

    HusPopup {
        id: enhancementRollPopup
        objectName: "enhancementRollOptions"
        parent: enhancementLuckyArrow
        y: enhancementLuckyArrow.height + 4
        x: enhancementLuckyArrow.width - width
        width: 410
        padding: 12
        modal: false
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        property var constraintOptions: ({})

        function indexOfValue(select, value) {
            if (value === undefined || value === null) return 0;
            for (var i = 0; i < select.model.length; i++)
                if (select.model[i].value === value) return i;
            return 0;
        }
        function currentConstraints() {
            return {
                "manufacturer": mfgSelect.model[mfgSelect.currentIndex].value,
                "rarity": raritySelect.model[raritySelect.currentIndex].value
            };
        }
        function refreshMatch() {
            var n = vmEnhancement.rollMatchCount(currentConstraints());
            matchText.text = n > 0
                    ? (vmEnhancement.rollTexts.matches || "Matching templates: {count}").replace("{count}", n)
                    : (vmEnhancement.rollTexts.no_matches || "No matching templates");
            rollNow.enabled = n > 0 && !vmEnhancement.rollBusy;
        }
        function openFor() {
            constraintOptions = vmEnhancement.rollConstraintOptions;
            open();
            var saved = vmEnhancement.rollConstraints || ({});
            mfgSelect.currentIndex = indexOfValue(mfgSelect, saved.manufacturer);
            raritySelect.currentIndex = indexOfValue(raritySelect, saved.rarity);
            countInput.value = Math.max(1, Math.min(50, vmEnhancement.rollCount || 5));
            refreshMatch();
        }
        contentItem: ColumnLayout {
            spacing: 8
            HusText { text: vmEnhancement.rollTexts.constraints_title || "Roll Options"; font.bold: true; color: HusTheme.Primary.colorTextBase }
            RowLayout {
                HusText { Layout.preferredWidth: 70; text: vmEnhancement.rollTexts.manufacturer || "Manufacturer"; color: HusTheme.Primary.colorTextSecondary }
                AppSelect { id: mfgSelect; Layout.fillWidth: true; model: enhancementRollPopup.constraintOptions.manufacturers || []; onActivated: enhancementRollPopup.refreshMatch() }
            }
            RowLayout {
                HusText { Layout.preferredWidth: 70; text: vmEnhancement.rollTexts.rarity || "Rarity"; color: HusTheme.Primary.colorTextSecondary }
                AppSelect { id: raritySelect; Layout.fillWidth: true; model: enhancementRollPopup.constraintOptions.rarities || []; onActivated: enhancementRollPopup.refreshMatch() }
            }
            RowLayout {
                HusText { Layout.preferredWidth: 70; text: vmEnhancement.rollTexts.count || "Count"; color: HusTheme.Primary.colorTextSecondary }
                HusInputInteger { id: countInput; min: 1; max: 50; value: 5; Layout.preferredWidth: 110 }
                HusText { id: matchText; Layout.fillWidth: true; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 12 }
            }
            HusButton {
                id: rollNow
                Layout.fillWidth: true
                text: vmEnhancement.rollTexts.roll || "Roll"
                type: HusButton.Type_Primary
                onClicked: if (vmEnhancement.startRoll(enhancementRollPopup.currentConstraints(), countInput.value)) enhancementRollPopup.close()
            }
        }
    }

    HusModal {
        id: enhancementRollDialog
        objectName: "enhancementRollDialog"
        width: 980
        height: 680
        closable: true
        colorBg: HusTheme.isDark ? "#1f242d" : "#f7f8fa"
        property bool hasResults: false
        function openResults() {
            title = vmEnhancement.rollTexts.results_title
            hasResults = true
            open()
        }
        contentDelegate: Item {
            implicitHeight: enhancementRollDialog.height - 4
            ModRollResultsView {
                anchors.fill: parent
                anchors.margins: 16
                results: enhancementRollDialog.hasResults ? vmEnhancement.rollResults : []
                texts: vmEnhancement.rollTexts
                canAdd: appBridge.saveLoaded
                onAddRequested: function(indices) { vmEnhancement.addLuckyRollToBackpack(indices); }
                onCopyRequested: function(index) { vmEnhancement.copyLuckyRoll(index); }
            }
        }
    }

    HusModal {
        id: base85Dialog
        width: 560
        closable: true
        title: vmEnhancement.sourceTexts.base85_title || ""
        confirmText: appBridge.trFormat("main_window.dialogs.confirm", {default: "OK"})
        cancelText: appBridge.trText("main_window.dialogs.cancel")
        onConfirm: { vmEnhancement.importBase85(base85Input.text); close(); }
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
}
