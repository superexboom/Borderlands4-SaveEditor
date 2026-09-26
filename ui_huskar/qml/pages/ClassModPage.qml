import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "../components"

// 职业模组编辑器页：对齐主线 QtClassModEditorTab
LockedFlickable {
    id: page
    objectName: "classModPage"
    enabled: !vmClassMod.rollBusy
    contentWidth: width
    contentHeight: column.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: HusScrollBar { }

    readonly property var vmLoc: vmClassMod.strings
    readonly property var topLoc: vmLoc.top_controls || ({})
    readonly property var outLoc: vmLoc.output || ({})

    SelectionStyle { id: selStyle }

    Connections {
        target: vmClassMod
        function onRollFinished(ok) {
            if (ok) classRollDialog.openResults()
        }
    }

    ColumnLayout {
        id: column
        width: page.width - 2
        spacing: 10

        // ---- 来源条 ----
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            HusText {
                text: vmClassMod.sourceText
                color: HusTheme.Primary.colorTextSecondary
                elide: Text.ElideMiddle
                Layout.fillWidth: true
            }
            HusIconButton {
                text: vmClassMod.sourceTexts.backpack || ""
                iconSource: HusIcon.InboxOutlined
                onClicked: { if (vmClassMod.prepareBackpackImport() > 0) backpackDialog.open(); }
            }
            HusIconButton {
                text: vmClassMod.sourceTexts.base85 || ""
                iconSource: HusIcon.LinkOutlined
                onClicked: base85Dialog.open()
            }
            HusIconButton {
                text: vmClassMod.sourceTexts.reset || ""
                iconSource: HusIcon.ReloadOutlined
                onClicked: vmClassMod.resetSource()
            }
        }

        // ---- 顶部控制：职业/稀有度/名称/等级/种子 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: topRow.implicitHeight + 28

            RowLayout {
                id: topRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                spacing: 10
                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true
                    HusText { text: topLoc.class || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    AppSelect {
                        Layout.fillWidth: true
                        model: vmClassMod.classOptions
                        currentIndex: vmClassMod.classIndex
                        enabled: !vmClassMod.importedCopy
                        onActivated: function(index) { vmClassMod.setClassIndex(index); }
                    }
                }
                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true
                    HusText { text: topLoc.rarity || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    AppSelect {
                        Layout.fillWidth: true
                        model: vmClassMod.rarityOptions
                        currentIndex: vmClassMod.rarityIndex
                        onActivated: function(index) { vmClassMod.setRarityIndex(index); }
                    }
                }
                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true
                    HusText { text: topLoc.name || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    AppSelect {
                        Layout.fillWidth: true
                        model: vmClassMod.nameOptions
                        currentIndex: vmClassMod.nameIndex
                        onActivated: function(index) { vmClassMod.setNameIndex(index); }
                    }
                }
                ColumnLayout {
                    spacing: 2
                    HusText { text: topLoc.level || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    HusInput {
                        Layout.preferredWidth: 70
                        text: vmClassMod.level
                        validator: IntValidator { bottom: 1; top: 999 }
                        onEditingFinished: vmClassMod.setLevel(text)
                    }
                }
                ColumnLayout {
                    spacing: 2
                    HusText { text: topLoc.seed || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    RowLayout {
                        spacing: 4
                        HusInput {
                            Layout.preferredWidth: 90
                            text: vmClassMod.seed
                            validator: IntValidator { bottom: 1; top: 9999 }
                            onEditingFinished: vmClassMod.setSeed(text)
                        }
                        HusIconButton {
                            iconSource: HusIcon.ReloadOutlined
                            contentDescription: "🎲"
                            onClicked: vmClassMod.randomizeSeed()
                        }
                    }
                }
            }
        }

        // ---- Legit 构筑状态（独立详情盒，紧跟职业控制） ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: classLegitRow.implicitHeight + 24
            visible: vmClassMod.dataLoaded

            RowLayout {
                id: classLegitRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 12
                spacing: 12
                LegitIndicator {
                    objectName: "classModLegitIndicator"
                    status: vmClassMod.legitBadge.status
                    label: vmClassMod.legitBadge.label
                    detail: vmClassMod.legitBadge.detail
                }
                HusText {
                    Layout.fillWidth: true
                    text: vmClassMod.legitBadge.detail || ""
                    color: HusTheme.Primary.colorTextSecondary
                    wrapMode: Text.Wrap
                    textFormat: Text.PlainText
                }
                RowLayout {
                    spacing: 4
                    HusButton {
                        objectName: "classModLuckyRoll"
                        text: "🎲 " + (vmClassMod.rollBusy
                              ? (vmClassMod.rollTexts.rolling || "生成中…")
                              : (vmClassMod.rollTexts.lucky || ""))
                        enabled: vmClassMod.dataLoaded && !vmClassMod.rollBusy
                        onClicked: vmClassMod.startQuickRoll()
                    }
                    HusIconButton {
                        id: classLuckyArrow
                        objectName: "classModLuckyArrow"
                        iconSource: HusIcon.DownOutlined
                        contentDescription: vmClassMod.rollTexts.constraints_title || ""
                        onClicked: classRollPopup.opened ? classRollPopup.close() : classRollPopup.openFor()
                    }
                }
            }
        }

        // ---- 输出 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: outputColumn.implicitHeight + 28

            ColumnLayout {
                id: outputColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                spacing: 8
                HusText { text: outLoc.title || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                RowLayout {
                    spacing: 8
                    HusText { Layout.preferredWidth: 86; text: outLoc.base85 || "Base85:"; color: HusTheme.Primary.colorTextSecondary }
                    HusInput {
                        Layout.fillWidth: true
                        readOnly: true
                        text: vmClassMod.base85Output
                        color: vmClassMod.encodeError ? HusTheme.Primary.colorError : HusTheme.Primary.colorTextBase
                    }
                    HusIconButton {
                        iconSource: HusIcon.CopyOutlined
                        onClicked: vmClassMod.copyBase85ToClipboard()
                    }
                    AppSelect {
                        Layout.preferredWidth: 150
                        model: vmClassMod.flagOptions
                        currentIndex: vmClassMod.flagIndex
                        onActivated: function(index) { vmClassMod.setFlagIndex(index); }
                    }
                    HusIconButton {
                        text: outLoc.add_to_backpack || ""
                        type: HusButton.Type_Primary
                        iconSource: HusIcon.PlusOutlined
                        enabled: !vmClassMod.encodeError && appBridge.saveLoaded
                        onClicked: vmClassMod.addToBackpack()
                    }
                }
                RowLayout {
                    spacing: 8
                    HusText { Layout.preferredWidth: 86; text: outLoc.deserialize || "Deserialize:"; color: HusTheme.Primary.colorTextSecondary }
                    HusInput {
                        Layout.fillWidth: true
                        readOnly: true
                        text: vmClassMod.rawOutput
                    }
                    HusIconButton {
                        iconSource: HusIcon.CopyOutlined
                        onClicked: vmClassMod.copyRawToClipboard()
                    }
                }
            }
        }

        // ---- 传奇附加 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: legPanel.implicitHeight + 28
            visible: vmClassMod.legendaryEnabled

            CatalogPickerPanel {
                id: legPanel
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                title: ((vmLoc.legendary || ({})).title || "") + " · " + vmClassMod.legendaryGuidance
                options: vmClassMod.legOptions
                categories: []
                entries: vmClassMod.legEntries
                stackable: false
                emphasizeLabels: true
                // Legendary name stays prominent; its effect text is secondary.
                emphasizeDetails: false
                clearText: (vmLoc.legendary || ({})).clear || "Clear"
                addText: appBridge.language === "zh-CN" ? "添加所选 →" : "Add selected →"
                availText: appBridge.language === "zh-CN" ? "可选" : "Available"
                selectedText: appBridge.language === "zh-CN" ? "已选" : "Selected"
                onAddRequested: function(keys) { vmClassMod.addLegItems(keys); }
                onRemoveRequested: function(index) { vmClassMod.removeLegItem(index); }
                onClearRequested: vmClassMod.clearLeg()
            }
        }

        // ---- 技能（对齐主线 InlineCatalogPicker：单列行内步进器，计数不可手输） ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: skillPanel.implicitHeight + 28

            InlineCatalogPanel {
                id: skillPanel
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                title: ((vmLoc.skills || ({})).title || "") + " · " + vmClassMod.skillGuidance
                options: vmClassMod.skillOptions
                categories: vmClassMod.skillCategories
                clearText: (vmLoc.perks || ({})).clear || "Clear"
                searchPlaceholder: (vmLoc.skills || ({})).search_placeholder || "🔍"
                editableCount: false
                multiSelect: false
                listHeight: 420
                onCountChanged: function(keys, value) { vmClassMod.setSkillCounts(keys, value); }
                onCountStepped: function(keys, delta) { vmClassMod.stepSkillCounts(keys, delta); }
                onClearRequested: vmClassMod.clearSkill()
            }
        }

        // ---- Perks（对齐主线：单列行内步进器，多选批量改数） ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: perkPanel.implicitHeight + 28

            InlineCatalogPanel {
                id: perkPanel
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                title: ((vmLoc.perks || ({})).title || "") + " · " + vmClassMod.perkGuidance
                options: vmClassMod.perkOptions
                categories: vmClassMod.perkCategories
                clearText: (vmLoc.perks || ({})).clear || "Clear"
                searchPlaceholder: (vmLoc.perks || ({})).search_placeholder || "🔍"
                editableCount: true
                multiSelect: true
                listHeight: 286
                onCountChanged: function(keys, value) { vmClassMod.setPerkCounts(keys, value); }
                onCountStepped: function(keys, delta) { vmClassMod.stepPerkCounts(keys, delta); }
                onClearRequested: vmClassMod.clearPerk()
            }
        }

        // ---- Special Thanks ----
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: thanksText.implicitHeight + 20
            visible: (vmClassMod.specialThanks.content || "") !== ""
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
                text: "<b>✨ " + (vmClassMod.specialThanks.title || "") + "</b><br>"
                      + (vmClassMod.specialThanks.content || "").replace(/\n/g, "<br>")
            }
        }

        Item { Layout.preferredHeight: 6 }
    }

    BackpackImportDialog { id: backpackDialog; vm: vmClassMod }

    HusPopup {
        id: classRollPopup
        objectName: "classModRollOptions"
        parent: classLuckyArrow
        y: classLuckyArrow.height + 4
        x: classLuckyArrow.width - width
        width: 450
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
        function syncNamedLock() {
            var named = nameSelect.currentIndex > 0 ? nameSelect.model[nameSelect.currentIndex] : null;
            if (named) {
                classSelect.currentIndex = indexOfValue(classSelect, named.classValue);
                raritySelect.currentIndex = indexOfValue(raritySelect, named.rarityValue);
            }
            classSelect.enabled = !named;
            raritySelect.enabled = !named;
        }
        function currentConstraints() {
            var named = nameSelect.currentIndex > 0 ? nameSelect.model[nameSelect.currentIndex].value : null;
            return {
                "class": classSelect.model[classSelect.currentIndex].value,
                "rarity": raritySelect.model[raritySelect.currentIndex].value,
                "name": named
            };
        }
        function refreshMatch() {
            var n = vmClassMod.rollMatchCount(currentConstraints());
            matchText.text = n > 0
                    ? (vmClassMod.rollTexts.matches || "Matching templates: {count}").replace("{count}", n)
                    : (vmClassMod.rollTexts.no_matches || "No matching templates");
            rollNow.enabled = n > 0 && !vmClassMod.rollBusy;
        }
        function openFor() {
            constraintOptions = vmClassMod.rollConstraintOptions;
            open();
            var saved = vmClassMod.rollConstraints || ({});
            classSelect.currentIndex = indexOfValue(classSelect, saved["class"]);
            raritySelect.currentIndex = indexOfValue(raritySelect, saved["rarity"]);
            nameSelect.currentIndex = indexOfValue(nameSelect, saved["name"]);
            countInput.value = Math.max(1, Math.min(50, vmClassMod.rollCount || 5));
            syncNamedLock();
            refreshMatch();
        }
        contentItem: ColumnLayout {
            spacing: 8
            HusText { text: vmClassMod.rollTexts.constraints_title || "Roll Options"; font.bold: true; color: HusTheme.Primary.colorTextBase }
            RowLayout {
                HusText { Layout.preferredWidth: 70; text: vmClassMod.rollTexts.class || "Class"; color: HusTheme.Primary.colorTextSecondary }
                AppSelect { id: classSelect; Layout.fillWidth: true; model: classRollPopup.constraintOptions.classes || []; onActivated: classRollPopup.refreshMatch() }
            }
            RowLayout {
                HusText { Layout.preferredWidth: 70; text: vmClassMod.rollTexts.rarity || "Rarity"; color: HusTheme.Primary.colorTextSecondary }
                AppSelect { id: raritySelect; Layout.fillWidth: true; model: classRollPopup.constraintOptions.rarities || []; onActivated: classRollPopup.refreshMatch() }
            }
            RowLayout {
                HusText { Layout.preferredWidth: 70; text: vmClassMod.rollTexts.named_item || "Named Class Mod"; color: HusTheme.Primary.colorTextSecondary }
                AppSelect { id: nameSelect; Layout.fillWidth: true; model: classRollPopup.constraintOptions.named_items || []; onActivated: { classRollPopup.syncNamedLock(); classRollPopup.refreshMatch(); } }
            }
            RowLayout {
                HusText { Layout.preferredWidth: 70; text: vmClassMod.rollTexts.count || "Count"; color: HusTheme.Primary.colorTextSecondary }
                HusInputInteger { id: countInput; min: 1; max: 50; value: 5; Layout.preferredWidth: 110 }
                HusText { id: matchText; Layout.fillWidth: true; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 12 }
            }
            HusButton {
                id: rollNow
                Layout.fillWidth: true
                text: vmClassMod.rollTexts.roll || "Roll"
                type: HusButton.Type_Primary
                onClicked: if (vmClassMod.startRoll(classRollPopup.currentConstraints(), countInput.value)) classRollPopup.close()
            }
        }
    }

    HusModal {
        id: classRollDialog
        objectName: "classModRollDialog"
        width: 980
        height: 680
        closable: true
        colorBg: HusTheme.isDark ? "#1f242d" : "#f7f8fa"
        property bool hasResults: false
        function openResults() {
            title = vmClassMod.rollTexts.results_title
            hasResults = true
            open()
        }
        contentDelegate: Item {
            implicitHeight: classRollDialog.height - 4
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 10
                ModRollResultsView {
                    id: rollView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    results: classRollDialog.hasResults ? vmClassMod.rollResults : []
                    texts: vmClassMod.rollTexts
                    canAdd: appBridge.saveLoaded
                    onAddRequested: function(indices) { vmClassMod.addLuckyRollToBackpack(indices); }
                    onCopyRequested: function(index) { vmClassMod.copyLuckyRoll(index); }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    HusText {
                        Layout.fillWidth: true
                        text: classRollDialog.hasResults ? vmClassMod.rollSummaryText : ""
                        color: HusTheme.Primary.colorTextSecondary
                        elide: Text.ElideRight
                    }
                    HusButton {
                        objectName: "classModRollAddAll"
                        text: vmClassMod.rollTexts.add_all || "Add All"
                        type: HusButton.Type_Primary
                        enabled: appBridge.saveLoaded && rollView.results.length > 0
                        onClicked: vmClassMod.addAllLuckyRolls()
                    }
                }
            }
        }
    }

    HusModal {
        id: base85Dialog
        width: 560
        closable: true
        title: vmClassMod.sourceTexts.base85_title || ""
        confirmText: appBridge.trFormat("main_window.dialogs.confirm", {default: "OK"})
        cancelText: appBridge.trText("main_window.dialogs.cancel")
        onConfirm: { vmClassMod.importBase85(base85Input.text); close(); }
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
