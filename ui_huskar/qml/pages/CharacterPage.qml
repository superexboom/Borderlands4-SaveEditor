import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "../components"

// 角色页：对齐主线 QtCharacterTab（离线字段/货币/预设 + live 运行时面板）
LockedFlickable {
    id: page
    contentWidth: width
    contentHeight: column.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: HusScrollBar { }

    readonly property var loc: vmCharacter.strings
    readonly property var labels: loc.labels || ({})
    readonly property var groups: loc.groups || ({})
    readonly property var buttons: loc.buttons || ({})

    function fillFields() {
        var f = vmCharacter.fields;
        if (!nameInput.activeFocus) nameInput.text = f["名称"] || "";
        if (!difficultyInput.activeFocus) difficultyInput.text = f["难度"] || "";
        if (!levelInput.activeFocus) levelInput.text = f["角色等级"] || "";
        if (!specLevelInput.activeFocus) specLevelInput.text = f["专精等级"] || "";
        if (!specPointsInput.activeFocus) specPointsInput.text = f["专精点数"] || "";
        if (!moneyInput.activeFocus) moneyInput.text = f["金钱"] || "";
        if (!eridiumInput.activeFocus) eridiumInput.text = f["镒矿"] || "";
    }

    Component.onCompleted: fillFields()

    Connections {
        target: vmCharacter
        function onDataChanged() { page.fillFields(); }
    }

    ColumnLayout {
        id: column
        width: page.width - 2
        spacing: 10

        HusEmpty {
            Layout.fillWidth: true
            height: 200
            visible: !vmCharacter.saveLoaded && !vmCharacter.liveMode
            description: appBridge.trText("main_window.dialogs.load_save_first")
        }

        // ---- 角色信息 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: infoColumn.implicitHeight + 32
            visible: !vmCharacter.liveMode && !vmCharacter.isProfileSave && vmCharacter.saveLoaded

            ColumnLayout {
                id: infoColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 16
                spacing: 8
                HusText { text: page.groups.character_info || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                // 主线 QFormLayout 排布：固定宽度标签列 + 输入列，每行一个字段
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 10
                    rowSpacing: 8
                    HusText { Layout.preferredWidth: 110; text: page.labels.name || ""; color: HusTheme.Primary.colorTextSecondary }
                    HusInput {
                        id: nameInput
                        Layout.fillWidth: true
                        onEditingFinished: vmCharacter.setField("名称", text)
                    }
                    HusText { Layout.preferredWidth: 110; text: page.labels.difficulty || ""; color: HusTheme.Primary.colorTextSecondary }
                    HusInput {
                        id: difficultyInput
                        Layout.fillWidth: true
                        onEditingFinished: vmCharacter.setField("难度", text)
                    }
                    HusText { Layout.preferredWidth: 110; text: page.labels.level || ""; color: HusTheme.Primary.colorTextSecondary }
                    RowLayout {
                        spacing: 8
                        HusInput {
                            id: levelInput
                            Layout.preferredWidth: 80
                            onTextChanged: if (activeFocus) vmCharacter.setField("角色等级", text)
                        }
                        HusText { text: page.labels.xp || ""; color: HusTheme.Primary.colorTextSecondary }
                        HusInput {
                            id: xpInput
                            Layout.preferredWidth: 120
                            readOnly: true
                            text: vmCharacter.xpValue
                        }
                        HusText {
                            text: page.labels.xp_auto_hint || ""
                            color: "#e0a040"
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                    HusText { Layout.preferredWidth: 110; text: page.labels.spec_level || ""; color: HusTheme.Primary.colorTextSecondary }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        HusInput {
                            id: specLevelInput
                            Layout.preferredWidth: 80
                            onTextChanged: if (activeFocus) vmCharacter.setField("专精等级", text)
                        }
                        HusText {
                            text: page.labels.spec_points || ""
                            color: HusTheme.Primary.colorTextSecondary
                        }
                        HusInput {
                            id: specPointsInput
                            Layout.preferredWidth: 120
                            readOnly: true
                            text: vmCharacter.specializationXpValue
                        }
                        HusText {
                            text: page.labels.xp_auto_hint || ""
                            color: "#e0a040"
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }

        // ---- 货币 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: currencyColumn.implicitHeight + 32
            visible: !vmCharacter.liveMode && vmCharacter.saveLoaded

            ColumnLayout {
                id: currencyColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 16
                spacing: 8
                HusText { text: page.groups.currency || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                // 主线 QFormLayout：标签列 + 输入列
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 10
                    rowSpacing: 8
                    HusText { Layout.preferredWidth: 110; visible: !vmCharacter.isProfileSave; text: page.labels.money || ""; color: HusTheme.Primary.colorTextSecondary }
                    HusInput {
                        id: moneyInput
                        visible: !vmCharacter.isProfileSave
                        Layout.fillWidth: true
                        onEditingFinished: vmCharacter.setField("金钱", text)
                    }
                    HusText { Layout.preferredWidth: 110; visible: !vmCharacter.isProfileSave; text: page.labels.eridium || ""; color: HusTheme.Primary.colorTextSecondary }
                    HusInput {
                        id: eridiumInput
                        visible: !vmCharacter.isProfileSave
                        Layout.fillWidth: true
                        onEditingFinished: vmCharacter.setField("镒矿", text)
                    }
                }
                Repeater {
                    id: vaultRepeater
                    model: vmCharacter.isProfileSave ? vmCharacter.vaultCurrencies : []
                    delegate: RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        HusText {
                            Layout.preferredWidth: 110
                            text: modelData.label
                            color: HusTheme.Primary.colorTextSecondary
                            elide: Text.ElideRight
                        }
                        HusInput {
                            Layout.fillWidth: true
                            text: modelData.value
                            validator: IntValidator { bottom: 0; top: 2147483647 }
                            onEditingFinished: vmCharacter.setField(modelData.key, text)
                        }
                    }
                }
            }
        }

        // ---- 操作 ----
        RowLayout {
            visible: !vmCharacter.liveMode && vmCharacter.saveLoaded
            spacing: 10
            HusButton {
                text: vmCharacter.isProfileSave ? (page.buttons.apply_profile_changes || "Apply")
                                                : (page.buttons.apply_changes || "Apply")
                type: HusButton.Type_Primary
                onClicked: vmCharacter.applyChanges()
            }
            HusButton {
                visible: !vmCharacter.isProfileSave
                text: page.buttons.sync_levels || ""
                onClicked: vmCharacter.syncLevels()
            }
            HusText {
                visible: !vmCharacter.isProfileSave
                text: (page.loc.warnings || ({})).sync_warning || ""
                color: "#e0a040"
                font.pixelSize: 11
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
        }

        HusText {
            visible: !vmCharacter.liveMode && vmCharacter.saveLoaded
            text: vmCharacter.presetModeHint
            color: "#f0c674"
            font.bold: true
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }

        // ---- 解锁预设 ----
        RowLayout {
            Layout.fillWidth: true
            visible: !vmCharacter.liveMode && vmCharacter.saveLoaded
            spacing: 10

            GlassPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: worldColumn.implicitHeight + 32
                ColumnLayout {
                    id: worldColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 16
                    spacing: 6
                    HusText { text: page.groups.world_presets || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                    Repeater {
                        model: vmCharacter.worldPresets
                        delegate: HusButton {
                            Layout.fillWidth: true
                            text: modelData.label
                            enabled: modelData.enabled
                            onClicked: vmCharacter.unlockPreset(modelData.action)
                        }
                    }
                    HusText {
                        text: page.labels.profile_only_hint || ""
                        color: HusTheme.Primary.colorTextTertiary
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Item { Layout.fillHeight: true }
                }
            }

            GlassPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: charColumn.implicitHeight + 32
                ColumnLayout {
                    id: charColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 16
                    spacing: 6
                    HusText { text: page.groups.char_presets || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                    Repeater {
                        model: vmCharacter.charPresets
                        delegate: HusButton {
                            Layout.fillWidth: true
                            text: modelData.label
                            enabled: modelData.enabled
                            onClicked: {
                                if (modelData.action === "change_class_popup")
                                    classDialog.open();
                                else
                                    vmCharacter.unlockPreset(modelData.action);
                            }
                        }
                    }
                    HusText {
                        text: page.labels.character_only_hint || ""
                        color: HusTheme.Primary.colorTextTertiary
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Item { Layout.fillHeight: true }
                }
            }
        }

        // ---- live 运行时面板 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: liveColumn.implicitHeight + 32
            visible: vmCharacter.liveMode

            ColumnLayout {
                id: liveColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 16
                spacing: 10
                HusText { text: page.groups.live_runtime || "Live"; font.bold: true; color: HusTheme.Primary.colorTextBase }
                HusText {
                    text: page.labels.live_runtime_hint || ""
                    color: HusTheme.Primary.colorTextSecondary
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }

                Repeater {
                    model: vmCharacter.liveSections
                    delegate: ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        property var section: modelData
                        HusText {
                            text: section.title
                            color: HusTheme.Primary.colorTextSecondary
                            font.bold: true
                        }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 8
                            Repeater {
                                model: section.buttons
                                delegate: HusButton {
                                    text: modelData.label
                                    checkable: modelData.checkable
                                    checked: modelData.checkable && modelData.checked
                                    enabled: !vmCharacter.runtimeBusy
                                    contentDescription: modelData.action === "toggle_dedicated_drop_100"
                                        ? (page.labels.live_dedicated_drop_hint || "")
                                        : (modelData.action === "max_sdu_tokens"
                                           ? (page.labels.live_max_sdu_tokens_hint || "") : "")
                                    onClicked: {
                                        if (modelData.checkable)
                                            vmCharacter.runToggle(modelData.action, checked);
                                        else
                                            vmCharacter.runAction(modelData.action);
                                    }
                                }
                            }
                        }
                    }
                }

                // 资源行：秘藏卡 / 货币 / 银行
                GridLayout {
                    Layout.fillWidth: true
                    columns: 4
                    columnSpacing: 10
                    rowSpacing: 8
                    HusText { text: page.labels.live_vault_card || ""; color: HusTheme.Primary.colorTextSecondary }
                    AppSelect {
                        id: vaultCardSelect
                        Layout.fillWidth: true
                        model: vmCharacter.liveVaultCards
                        textRole: "label"
                    }
                    HusInput {
                        id: vaultCardLevel
                        Layout.preferredWidth: 90
                        validator: IntValidator { bottom: 0; top: 9999999 }
                    }
                    HusButton {
                        text: page.buttons.set_vault_card_level || "Set"
                        enabled: vaultCardSelect.count > 0 && vaultCardLevel.text.trim() !== "" && !vmCharacter.runtimeBusy
                        onClicked: vmCharacter.setVaultCardLevel(vaultCardSelect.currentIndex, parseInt(vaultCardLevel.text))
                    }
                    HusText { text: page.labels.live_currency || ""; color: HusTheme.Primary.colorTextSecondary }
                    AppSelect {
                        id: currencySelect
                        Layout.fillWidth: true
                        model: vmCharacter.liveCurrencies
                        textRole: "label"
                    }
                    HusInput {
                        id: currencyAmount
                        Layout.preferredWidth: 90
                        text: "1000"
                        validator: IntValidator { bottom: 1; top: 2147483647 }
                    }
                    HusButton {
                        text: page.buttons.give_currency || "Add"
                        enabled: currencySelect.count > 0 && currencyAmount.text.trim() !== "" && !vmCharacter.runtimeBusy
                        onClicked: vmCharacter.giveCurrency(currencySelect.currentIndex, parseInt(currencyAmount.text))
                    }
                    HusText { text: page.labels.bank_size || ""; color: HusTheme.Primary.colorTextSecondary }
                    Item { Layout.fillWidth: true }
                    HusInput {
                        id: bankSize
                        Layout.preferredWidth: 90
                        validator: IntValidator { bottom: 1; top: 5000 }
                    }
                    HusButton {
                        text: page.buttons.apply_bank_size || "Apply"
                        enabled: bankSize.text.trim() !== "" && !vmCharacter.runtimeBusy
                        onClicked: vmCharacter.runActionWithValue("set_bank_size", parseInt(bankSize.text))
                    }
                }

                // 数值调节
                HusText { text: page.labels.live_tuning || ""; color: HusTheme.Primary.colorTextSecondary; font.bold: true }
                Repeater {
                    model: vmCharacter.liveTuning
                    delegate: RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        HusText {
                            Layout.preferredWidth: 220
                            text: modelData.label
                            color: HusTheme.Primary.colorTextSecondary
                            elide: Text.ElideRight
                        }
                        AppSelect {
                            Layout.fillWidth: true
                            model: modelData.options
                            currentIndex: Math.max(0, modelData.options.findIndex(function(o){ return o.value === modelData.value; }))
                            onActivated: function(index) { vmCharacter.runActionWithValue(modelData.action, model[index].value); }
                        }
                    }
                }
                RowLayout {
                    spacing: 10
                    HusText { Layout.preferredWidth: 220; text: page.labels.backpack_size || ""; color: HusTheme.Primary.colorTextSecondary }
                    HusInput {
                        id: backpackSize
                        Layout.fillWidth: true
                        text: "999"
                        validator: IntValidator { bottom: 20; top: 5000 }
                    }
                    HusButton {
                        text: page.buttons.apply_backpack_size || "Apply"
                        enabled: !vmCharacter.runtimeBusy
                        onClicked: vmCharacter.runActionWithValue("set_backpack_size", parseInt(backpackSize.text))
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 6
                    columnSpacing: 8
                    rowSpacing: 8
                    HusText { text: page.labels.magazine_capacity_scale || ""; color: HusTheme.Primary.colorTextSecondary }
                    HusInput { id: magCap; Layout.fillWidth: true; text: "1"; validator: DoubleValidator { bottom: 0.1; top: 100; decimals: 2 } }
                    HusButton { text: page.buttons.apply_magazine_capacity || "Apply"; onClicked: vmCharacter.runActionWithValue("set_magazine_capacity_scale", parseFloat(magCap.text)) }
                    HusText { text: page.labels.projectile_speed_scale || ""; color: HusTheme.Primary.colorTextSecondary }
                    HusInput { id: projSpeed; Layout.fillWidth: true; text: "1"; validator: DoubleValidator { bottom: 0.1; top: 100; decimals: 2 } }
                    HusButton { text: page.buttons.apply_projectile_speed || "Apply"; onClicked: vmCharacter.runActionWithValue("set_projectile_speed_scale", parseFloat(projSpeed.text)) }
                }

                // 位置书签
                HusText { text: page.labels.live_position || ""; color: HusTheme.Primary.colorTextSecondary; font.bold: true }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    HusText {
                        Layout.fillWidth: true
                        text: vmCharacter.positionText
                        color: HusTheme.Primary.colorTextSecondary
                        wrapMode: Text.Wrap
                    }
                    HusButton {
                        text: page.buttons.refresh_position || "Refresh"
                        onClicked: vmCharacter.runAction("position_state")
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    HusInput {
                        id: bookmarkName
                        Layout.fillWidth: true
                        placeholderText: page.labels.bookmark_name || ""
                    }
                    HusButton {
                        text: page.buttons.save_position || "Save"
                        onClicked: { vmCharacter.saveBookmark(bookmarkName.text); bookmarkName.text = ""; }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    AppSelect {
                        id: bookmarkSelect
                        Layout.fillWidth: true
                        model: vmCharacter.bookmarkModel
                        textRole: "label"
                    }
                    HusButton {
                        text: page.buttons.teleport_position || "Teleport"
                        enabled: bookmarkSelect.count > 0 && !vmCharacter.runtimeBusy
                        onClicked: vmCharacter.teleportBookmark(bookmarkSelect.currentIndex)
                    }
                    HusButton {
                        text: page.buttons.delete_position || "Delete"
                        enabled: bookmarkSelect.count > 0
                        onClicked: vmCharacter.deleteBookmark(bookmarkSelect.currentIndex)
                    }
                }

                // 失物
                HusText { text: page.labels.live_lost_loot || ""; color: HusTheme.Primary.colorTextSecondary; font.bold: true }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    HusText {
                        Layout.fillWidth: true
                        text: vmCharacter.lostLootText
                        color: HusTheme.Primary.colorTextSecondary
                        wrapMode: Text.Wrap
                    }
                    HusButton {
                        text: page.buttons.refresh_lost_loot || "Refresh"
                        onClicked: vmCharacter.runAction("lost_loot_state")
                    }
                    HusButton {
                        text: page.buttons.claim_lost_loot || "Claim"
                        enabled: vmCharacter.canClaimLostLoot
                        onClicked: vmCharacter.runAction("claim_lost_loot")
                    }
                }

                HusText {
                    text: vmCharacter.runtimeStatus
                    color: vmCharacter.runtimeStatusOk ? "#78dba9" : "#ff6b6b"
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }
        }

        Item { Layout.preferredHeight: 6 }
    }

    // 更换职业对话框
    HusModal {
        id: classDialog
        anchors.centerIn: parent
        width: 380
        title: (page.loc.dialogs || ({})).change_class_title || ""
        confirmText: appBridge.trFormat("main_window.dialogs.confirm", {default: "OK"})
        cancelText: appBridge.trText("main_window.dialogs.cancel")
        onConfirm: {
            vmCharacter.changeClass(classSelect.model[classSelect.currentIndex].key);
            close();
        }
        onCancel: close()
        contentDelegate: Item {
            implicitHeight: classColumn.implicitHeight
            ColumnLayout {
                id: classColumn
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: 10
                HusText {
                    text: (page.loc.dialogs || ({})).select_class || ""
                    color: HusTheme.Primary.colorTextBase
                }
                AppSelect {
                    id: classSelect
                    Layout.fillWidth: true
                    model: vmCharacter.classOptions
                    textRole: "label"
                }
            }
        }
    }
}
