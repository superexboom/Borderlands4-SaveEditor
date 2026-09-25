import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "../components"

// 武器生成器页：对齐主线 QtWeaponGeneratorTab
LockedFlickable {
    id: page
    contentWidth: width
    contentHeight: column.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: HusScrollBar { }

    readonly property var vmLoc: vmWeaponGenerator.strings
    readonly property var labelsLoc: vmLoc.labels || ({})
    readonly property var buttonsLoc: vmLoc.buttons || ({})
    readonly property var sections: vmWeaponGenerator.sectionTexts

    // HusSelect drops a declarative currentIndex binding after a user activation.
    // Re-apply the VM index after a manufacturer/type rebuild so a previous
    // rarity never leaks into the next weapon family.
    Connections {
        target: vmWeaponGenerator
        function onDataChanged() {
            Qt.callLater(function() {
                if (generatorRaritySelect && generatorRaritySelect.count > 0)
                    generatorRaritySelect.currentIndex = vmWeaponGenerator.rarityIndex;
            });
        }
    }

    ColumnLayout {
        id: column
        width: page.width - 2
        spacing: 10

        EmptyHint {
            Layout.fillWidth: true
            Layout.preferredHeight: 160
            visible: !vmWeaponGenerator.dataLoaded
            description: vmWeaponGenerator.loadErrorText
        }

        // ---- 输出 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: outputColumn.implicitHeight + 28
            visible: vmWeaponGenerator.dataLoaded

            ColumnLayout {
                id: outputColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                spacing: 8
                RowLayout {
                    spacing: 8
                    HusText { Layout.preferredWidth: 86; text: labelsLoc.serial_decoded || "Deserialize:"; color: HusTheme.Primary.colorTextSecondary }
                    HusInput { Layout.fillWidth: true; readOnly: true; text: vmWeaponGenerator.decodedOutput }
                    HusIconButton { iconSource: HusIcon.CopyOutlined; onClicked: vmWeaponGenerator.copyRawToClipboard() }
                }
                RowLayout {
                    spacing: 8
                    HusText { Layout.preferredWidth: 86; text: labelsLoc.serial_b85 || "Base85:"; color: HusTheme.Primary.colorTextSecondary }
                    HusInput {
                        Layout.fillWidth: true
                        readOnly: true
                        text: vmWeaponGenerator.base85Output
                        color: vmWeaponGenerator.encodeError ? HusTheme.Primary.colorError : HusTheme.Primary.colorTextBase
                    }
                    HusIconButton { iconSource: HusIcon.CopyOutlined; onClicked: vmWeaponGenerator.copyBase85ToClipboard() }
                }
            }
        }

        // ---- 配置卡片 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: configColumn.implicitHeight + 28
            visible: vmWeaponGenerator.dataLoaded

            ColumnLayout {
                id: configColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                spacing: 8
                RowLayout {
                    spacing: 8
                    HusText { text: sections.config || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                    // 构建状态指示器（武器配置标题右侧）+ 当前缺失配件列表
                    HusTag {
                        id: ruleTag
                        text: vmWeaponGenerator.ruleBadge.text
                        presetColor: vmWeaponGenerator.ruleBadge.status === "legal" ? "green"
                                   : vmWeaponGenerator.ruleBadge.status === "unknown" ? "default" : "orange"
                        HoverHandler {
                            onHoveredChanged: if (hovered) HoverTip.showFor(ruleTag, vmWeaponGenerator.ruleBadge.tooltip || "", ruleTag.width / 2, ruleTag.height)
                                              else HoverTip.hideFor(ruleTag)
                        }
                    }
                    HusText {
                        visible: vmWeaponGenerator.missingPartsText !== ""
                        text: vmWeaponGenerator.missingPartsText
                        color: "#e6a439"
                        font.pixelSize: 11
                        elide: Text.ElideRight
                        Layout.maximumWidth: 520
                    }
                    Item { Layout.fillWidth: true }
                    RowLayout {
                        spacing: 4
                        HusButton {
                            objectName: "weaponQuickRoll"
                            text: "🎲 " + (buttonsLoc.lucky || "")
                            onClicked: page.quickRoll()
                        }
                        HusIconButton {
                            id: rollArrow
                            objectName: "weaponRollArrow"
                            iconSource: HusIcon.DownOutlined
                            contentDescription: vmWeaponGenerator.rollTexts.constraints_title
                            onClicked: {
                                rollDialog.constraintOptions = vmWeaponGenerator.rollConstraintOptions();
                                rollOptions.openFor();
                            }
                        }
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 6
                    columnSpacing: 10
                    rowSpacing: 4
                    HusText { text: labelsLoc.manufacturer || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    HusText { text: labelsLoc.weapon_type || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    HusText { text: labelsLoc.level || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    HusText { text: labelsLoc.seed || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    HusText { text: labelsLoc.select_flag || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    HusText { text: ""; }
                    AppSelect {
                        Layout.fillWidth: true
                        model: vmWeaponGenerator.mfgOptions
                        currentIndex: vmWeaponGenerator.mfgIndex
                        onActivated: function(index) { vmWeaponGenerator.setMfgIndex(index); }
                    }
                    AppSelect {
                        Layout.fillWidth: true
                        model: vmWeaponGenerator.weaponTypeOptions
                        currentIndex: vmWeaponGenerator.weaponTypeIndex
                        onActivated: function(index) { vmWeaponGenerator.setWeaponTypeIndex(index); }
                    }
                    HusInput {
                        Layout.preferredWidth: 70
                        text: vmWeaponGenerator.level
                        validator: IntValidator { bottom: 1; top: 999 }
                        onEditingFinished: vmWeaponGenerator.setLevel(text)
                    }
                    RowLayout {
                        spacing: 4
                        HusInput {
                            Layout.fillWidth: true
                            text: vmWeaponGenerator.seed
                            validator: IntValidator { bottom: 1; top: 9999 }
                            onEditingFinished: vmWeaponGenerator.setSeed(text)
                        }
                        HusIconButton {
                            iconSource: HusIcon.ReloadOutlined
                            contentDescription: "🎲"
                            onClicked: vmWeaponGenerator.randomizeSeed()
                        }
                    }
                    AppSelect {
                        Layout.fillWidth: true
                        model: vmWeaponGenerator.flagOptions
                        currentIndex: vmWeaponGenerator.flagIndex
                        onActivated: function(index) { vmWeaponGenerator.setFlagIndex(index); }
                    }
                    HusIconButton {
                        text: buttonsLoc.add_to_backpack || ""
                        type: HusButton.Type_Primary
                        iconSource: HusIcon.PlusOutlined
                        enabled: !vmWeaponGenerator.encodeError && appBridge.saveLoaded
                        onClicked: vmWeaponGenerator.addToBackpack()
                    }
                }
            }
        }

        // ---- 属性统计（默认折叠，构建状态已移至武器配置标题右侧） ----
        GlassPanel {
            id: statsCard
            Layout.fillWidth: true
            Layout.preferredHeight: statsColumn.implicitHeight + 28
            visible: vmWeaponGenerator.dataLoaded
            property bool expanded: false

            ColumnLayout {
                id: statsColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                spacing: 8
                RowLayout {
                    spacing: 6
                    HusText {
                        text: sections.stats || "Stats"
                        font.bold: true
                        color: HusTheme.Primary.colorTextBase
                        Layout.fillWidth: true
                    }
                    HusIconButton {
                        iconSource: statsCard.expanded ? HusIcon.UpOutlined : HusIcon.DownOutlined
                        contentDescription: sections.stats || "Stats"
                        onClicked: statsCard.expanded = !statsCard.expanded
                    }
                }
                GridLayout {
                    id: statsGrid
                    Layout.fillWidth: true
                    visible: statsCard.expanded
                    columns: 6
                    columnSpacing: 12
                    rowSpacing: 6
                    Repeater {
                        model: vmWeaponGenerator.statsPreview
                        delegate: Column {
                            // fillWidth 让 6 列均分整行，否则全挤到最左边
                            Layout.fillWidth: true
                            spacing: 1
                            HusText {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.label
                                color: HusTheme.Primary.colorTextSecondary
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                            HusText {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.value
                                color: HusTheme.Primary.colorTextBase
                                font.bold: true
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }
        }

        // ---- 属性卡片 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: attrColumn.implicitHeight + 28
            visible: vmWeaponGenerator.dataLoaded

            ColumnLayout {
                id: attrColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                spacing: 8
                RowLayout {
                    HusText { text: sections.attributes || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                    Item { Layout.fillWidth: true }
                    HusText { text: sections.available_only || ""; color: HusTheme.Primary.colorTextTertiary; font.pixelSize: 11 }
                }
                RowLayout {
                    spacing: 10
                    ColumnLayout {
                        spacing: 2
                        Layout.fillWidth: true
                        HusText { text: labelsLoc.rarity || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        AppSelect {
                            id: generatorRaritySelect
                            Layout.fillWidth: true
                            model: vmWeaponGenerator.rarityOptions
                            currentIndex: vmWeaponGenerator.rarityIndex
                            onActivated: function(index) { vmWeaponGenerator.setRarityIndex(index); }
                        }
                    }
                    ColumnLayout {
                        spacing: 2
                        Layout.fillWidth: true
                        visible: vmWeaponGenerator.legendaryVisible
                        HusText { text: labelsLoc.named_weapon || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        AppSelect {
                            Layout.fillWidth: true
                            model: vmWeaponGenerator.legendaryTypeOptions
                            currentIndex: vmWeaponGenerator.legendaryTypeIndex
                            onActivated: function(index) { vmWeaponGenerator.setLegendaryTypeIndex(index); }
                        }
                    }
                    ColumnLayout {
                        spacing: 2
                        Layout.fillWidth: true
                        visible: vmWeaponGenerator.pearlTypeVisible
                        HusText { text: labelsLoc.named_weapon || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        AppSelect {
                            Layout.fillWidth: true
                            model: vmWeaponGenerator.pearlTypeOptions
                            currentIndex: vmWeaponGenerator.pearlTypeIndex
                            onActivated: function(index) { vmWeaponGenerator.setPearlTypeIndex(index); }
                        }
                    }
                }

                // 元素1 芯片（legit 以上色呈现，对齐主线候选配色）
                RowLayout {
                    spacing: 10
                    HusText { Layout.preferredWidth: 64; text: labelsLoc.main_element || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 6
                        Repeater {
                            model: vmWeaponGenerator.element1Options
                            delegate: LegitChip {
                                text: modelData.label.indexOf(" - ") >= 0 ? modelData.label.split(" - ").slice(1).join(" - ") : modelData.label
                                fullText: modelData.label
                                checked: vmWeaponGenerator.element1Index === index
                                kind: modelData.kind || ""
                                onClicked: vmWeaponGenerator.setElement1Index(index)
                            }
                        }
                    }
                }

                // 元素2 芯片
                RowLayout {
                    visible: vmWeaponGenerator.element2Visible
                    spacing: 10
                    HusText { Layout.preferredWidth: 64; text: labelsLoc.secondary_element || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 6
                        Repeater {
                            model: vmWeaponGenerator.element2Options
                            delegate: LegitChip {
                                text: modelData.label.indexOf(" - ") >= 0 ? modelData.label.split(" - ").slice(1).join(" - ") : modelData.label
                                fullText: modelData.label
                                checked: vmWeaponGenerator.element2Index === index
                                kind: modelData.kind || ""
                                onClicked: vmWeaponGenerator.setElement2Index(index)
                            }
                        }
                    }
                }

                // 珠光
                RowLayout {
                    visible: vmWeaponGenerator.pearlVisible
                    spacing: 10
                    ColumnLayout {
                        spacing: 2
                        Layout.fillWidth: true
                        HusText { text: sections.pearl_stat || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 6
                            Repeater {
                                model: vmWeaponGenerator.pearlStatOptions
                                delegate: LegitChip {
                                    text: modelData.label.indexOf(" - ") >= 0 ? modelData.label.split(" - ").slice(1).join(" - ") : modelData.label
                                    fullText: modelData.label
                                    checked: vmWeaponGenerator.pearlStatIndex === index
                                    kind: modelData.kind || ""
                                    onClicked: vmWeaponGenerator.setPearlStatIndex(index)
                                }
                            }
                        }
                    }
                    ColumnLayout {
                        spacing: 2
                        Layout.fillWidth: true
                        HusText { text: sections.pearl_elements || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 6
                            Repeater {
                                model: vmWeaponGenerator.pearlElementOptions
                                delegate: LegitChip {
                                    text: modelData.label.indexOf(" - ") >= 0 ? modelData.label.split(" - ").slice(1).join(" - ") : modelData.label
                                    fullText: modelData.label
                                    checked: vmWeaponGenerator.pearlElementIndex === index
                                    kind: modelData.kind || ""
                                    onClicked: vmWeaponGenerator.setPearlElementIndex(index)
                                }
                            }
                        }
                    }
                }

                HusDivider { Layout.fillWidth: true }
                HusText {
                    text: sections.attribute_hint || ""
                    color: HusTheme.Primary.colorTextTertiary
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }
        }

        // ---- 部件容器 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: partsGrid.implicitHeight + 28
            visible: vmWeaponGenerator.dataLoaded

            GridLayout {
                id: partsGrid
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                columns: 2
                columnSpacing: 12
                rowSpacing: 8

                Repeater {
                    model: vmWeaponGenerator.partGroups
                    delegate: ColumnLayout {
                        Layout.fillWidth: true
                        // GridLayout 按各列 implicitWidth 比例分配宽度，配件说明长文本会
                        // 顶宽所在列（下拉栏宽度到处飞）；统一 preferredWidth 让两列始终均分
                        Layout.preferredWidth: 1
                        Layout.row: modelData.row
                        Layout.column: modelData.col
                        visible: modelData.visible
                        spacing: 4
                        RowLayout {
                            HusText {
                                text: modelData.title
                                font.bold: true
                                color: HusTheme.Primary.colorTextBase
                            }
                            Item { Layout.fillWidth: true }
                            HusTag {
                                id: partTag
                                text: modelData.badge
                                // geekblue/processing 深色模式下都是暗色读不清；自定义实心强调蓝+白字
                                presetColor: "#4a90e2"
                                HoverHandler {
                                    onHoveredChanged: if (hovered) HoverTip.showFor(partTag, modelData.badgeTip || "", partTag.width / 2, partTag.height)
                                                      else HoverTip.hideFor(partTag)
                                }
                            }
                        }
                        Repeater {
                            model: modelData.slots
                            delegate: ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                AppSelect {
                                    Layout.fillWidth: true
                                    model: modelData.options
                                    currentIndex: modelData.selectedIndex
                                    onActivated: function(index) { vmWeaponGenerator.setPartSelection(modelData.key, index); }
                                }
                                HusText {
                                    visible: modelData.detail !== ""
                                    text: modelData.detail
                                    color: HusTheme.Primary.colorTextSecondary
                                    font.pixelSize: 11
                                    wrapMode: Text.Wrap
                                    Layout.fillWidth: true
                                }
                            }
                        }
                    }
                }
            }
        }

        Item { Layout.preferredHeight: 6 }
    }

    property var rollConstraints: ({manufacturer:null, weapon_type:null, rarity:null})
    property int rollCountValue: 5
    function quickRoll() {
        if (vmWeaponGenerator.roll(rollConstraints, rollCountValue)) rollDialog.openResults();
    }
    HusPopup {
        id: rollOptions
        objectName: "weaponRollOptions"
        parent: Overlay.overlay
        width: Math.min(420, parent ? parent.width - 24 : 420)
        padding: 16
        colorBg: HusTheme.isDark ? "#1f242d" : "#f7f8fa"
        function openFor() {
            var p = rollArrow.mapToItem(parent, 0, rollArrow.height + 4);
            x = Math.max(8, Math.min(p.x + rollArrow.width - width, parent.width-width-8));
            y = Math.max(8, Math.min(p.y, parent.height-height-8));
            open();
        }
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        contentItem: ColumnLayout {
                    spacing: 8
                    HusText { text: vmWeaponGenerator.rollTexts.constraints_title; font.bold: true; font.pixelSize: 16; color: HusTheme.Primary.colorTextBase }
                    HusText { text: vmWeaponGenerator.rollTexts.manufacturer; color: HusTheme.Primary.colorTextSecondary }
                    AppSelect {
                        id: rollMfg
                        Layout.fillWidth: true
                        model: rollDialog.constraintOptions ? rollDialog.constraintOptions.manufacturers : []
                    }
                    HusText { text: vmWeaponGenerator.rollTexts.weapon_type; color: HusTheme.Primary.colorTextSecondary }
                    AppSelect {
                        id: rollType
                        Layout.fillWidth: true
                        model: rollDialog.constraintOptions ? rollDialog.constraintOptions.weapon_types : []
                    }
                    HusText { text: vmWeaponGenerator.rollTexts.rarity; color: HusTheme.Primary.colorTextSecondary }
                    AppSelect {
                        id: rollRarity
                        Layout.fillWidth: true
                        model: rollDialog.constraintOptions ? rollDialog.constraintOptions.rarities : []
                    }
                    HusText { text: vmWeaponGenerator.rollTexts.count; color: HusTheme.Primary.colorTextSecondary }
                    HusInputInteger { id: rollCount; min: 1; max: 50; value: 5; Layout.preferredWidth: 110 }
                    HusButton {
                        Layout.fillWidth: true
                        text: vmWeaponGenerator.rollTexts.roll
                        type: HusButton.Type_Primary
                        onClicked: {
                            var constraints = {
                                manufacturer: rollMfg.model[rollMfg.currentIndex].value,
                                weapon_type: rollType.model[rollType.currentIndex].value,
                                rarity: rollRarity.model[rollRarity.currentIndex].value,
                            };
                            page.rollConstraints = constraints;
                            page.rollCountValue = rollCount.value;
                            rollOptions.close();
                            page.quickRoll();
                        }
                    }
                }
    }

    // ---- Roll 对话框 ----
    HusModal {
        id: rollDialog
        width: 900
        height: 640
        closable: true
        colorBg: HusTheme.isDark ? "#1f242d" : "#f7f8fa"

        property var constraintOptions: null
        property bool hasResults: false

        function openResults() {
            title = vmWeaponGenerator.rollTexts.results_title;
            hasResults = true;
            open();
        }

        contentDelegate: Item {
            // 高度拉满弹窗（消除底部空白），四周留白
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
                    text: vmWeaponGenerator.rollSummaryText
                    color: HusTheme.Primary.colorTextSecondary
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
                RollResultsView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: rollDialog.hasResults
                    results: rollDialog.hasResults ? vmWeaponGenerator.rollResults : []
                    texts: vmWeaponGenerator.rollTexts
                    canAdd: appBridge.saveLoaded
                    onAddRequested: function(indices) { vmWeaponGenerator.addRollToBackpack(indices); }
                    onCopyRequested: function(index) { vmWeaponGenerator.copyRollResult(index); }
                }
                RowLayout {
                    visible: rollDialog.hasResults
                    spacing: 8
                    Item { Layout.fillWidth: true }
                    HusButton {
                        text: vmWeaponGenerator.rollTexts.add_all
                        type: HusButton.Type_Primary
                        enabled: appBridge.saveLoaded
                        onClicked: {
                            var indices = [];
                            for (var i = 0; i < vmWeaponGenerator.rollResults.length; i++) indices.push(i);
                            vmWeaponGenerator.addRollToBackpack(indices);
                        }
                    }
                }
            }
        }
    }
}
