import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "../components"

// God Roll 优化器页：对齐主线 QtGodRollTab
Item {
    id: page
    readonly property var t: vmGodRoll.texts
    SelectionStyle { id: selStyle }

    // ================= 配置页 =================
    LockedFlickable {
        anchors.fill: parent
        visible: !vmGodRoll.resultsVisible
        contentWidth: width
        contentHeight: configColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: HusScrollBar { }

        ColumnLayout {
            id: configColumn
            width: parent.width - 2
            spacing: 10

            HusText {
                visible: vmGodRoll.liveMode
                text: t.offline_only || ""
                color: "#FFB74D"
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            // ---- 目标武器 ----
            GlassPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: sourceColumn.implicitHeight + 28

                ColumnLayout {
                    id: sourceColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    spacing: 6
                    HusText { text: t.title || ""; font.bold: true; font.pixelSize: 15; color: HusTheme.Primary.colorTextBase }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 3
                        columnSpacing: 10
                        rowSpacing: 4
                        HusText { text: t.rarity || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        HusText { text: t.manufacturer || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        HusText { text: t.weapon_type || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        AppSelect {
                            Layout.fillWidth: true
                            model: vmGodRoll.rarityOptions
                            currentIndex: vmGodRoll.rarityIndex
                            enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                            onActivated: function(index) { vmGodRoll.setRarityIndex(index); }
                        }
                        AppSelect {
                            Layout.fillWidth: true
                            model: vmGodRoll.mfgOptions
                            currentIndex: vmGodRoll.mfgIndex
                            enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                            onActivated: function(index) { vmGodRoll.setMfgIndex(index); }
                        }
                        AppSelect {
                            Layout.fillWidth: true
                            model: vmGodRoll.weaponTypeOptions
                            currentIndex: vmGodRoll.weaponTypeIndex
                            enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                            onActivated: function(index) { vmGodRoll.setWeaponTypeIndex(index); }
                        }
                        HusText { text: t.weapon || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        HusText { text: t.mode || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        RowLayout {
                            spacing: 8
                            HusText { text: t.level || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                            HusText { text: t.select_flag || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        }
                        AppSelect {
                            Layout.fillWidth: true
                            model: vmGodRoll.weaponOptions
                            currentIndex: vmGodRoll.weaponIndex
                            enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                            onActivated: function(index) { vmGodRoll.setWeaponIndex(index); }
                        }
                        AppSelect {
                            Layout.fillWidth: true
                            model: vmGodRoll.modeOptions
                            currentIndex: vmGodRoll.modeIndex
                            enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                            onActivated: function(index) { vmGodRoll.setModeIndex(index); }
                        }
                        RowLayout {
                            spacing: 8
                            HusInputInteger {
                                Layout.fillWidth: true
                                min: 1
                                max: 999
                                value: vmGodRoll.level
                                enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                                onValueModified: vmGodRoll.setLevel(value)
                            }
                            AppSelect {
                                Layout.fillWidth: true
                                model: vmGodRoll.flagOptions
                                currentIndex: vmGodRoll.flagIndex
                                onActivated: function(index) { vmGodRoll.setFlagIndex(index); }
                            }
                        }
                    }
                }
            }

            // ---- 约束 ----
            GlassPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: constraintGrid.implicitHeight + 28

                GridLayout {
                    id: constraintGrid
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    columns: 3
                    columnSpacing: 10
                    rowSpacing: 4
                    HusText { text: t.barrel || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    HusText { text: t.torgue || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    HusText { text: t.base_element || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    AppSelect {
                        Layout.fillWidth: true
                        model: vmGodRoll.barrelOptions
                        currentIndex: vmGodRoll.barrelIndex
                        enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                        onActivated: function(index) { vmGodRoll.setBarrelIndex(index); }
                    }
                    AppSelect {
                        Layout.fillWidth: true
                        model: vmGodRoll.torgueOptions
                        currentIndex: vmGodRoll.torgueIndex
                        enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                        onActivated: function(index) { vmGodRoll.setTorgueIndex(index); }
                    }
                    AppSelect {
                        Layout.fillWidth: true
                        model: vmGodRoll.baseElementOptions
                        currentIndex: vmGodRoll.baseElementIndex
                        enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                        onActivated: function(index) { vmGodRoll.setBaseElementIndex(index); }
                    }
                    HusText { text: t.secondary_element || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    HusText { text: t.pearl_element || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    HusText { text: ""; }
                    AppSelect {
                        Layout.fillWidth: true
                        model: vmGodRoll.secondaryElementOptions
                        currentIndex: vmGodRoll.secondaryElementIndex
                        enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                        onActivated: function(index) { vmGodRoll.setSecondaryElementIndex(index); }
                    }
                    AppSelect {
                        Layout.fillWidth: true
                        model: vmGodRoll.pearlElementOptions
                        currentIndex: vmGodRoll.pearlElementIndex
                        enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                        onActivated: function(index) { vmGodRoll.setPearlElementIndex(index); }
                    }
                    HusText { text: ""; }
                    HusCheckBox {
                        Layout.columnSpan: 3
                        text: t.force_element || ""
                        checked: vmGodRoll.forceElement
                        contentDescription: t.force_hint || ""
                        enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                        onToggled: vmGodRoll.setForceElement(checked)
                    }
                    HusText {
                        Layout.columnSpan: 3
                        text: t.score_note || ""
                        color: HusTheme.Primary.colorTextTertiary
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }

            // ---- 组限制（unrestricted） ----
            GlassPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: limitsColumn.implicitHeight + 28
                visible: vmGodRoll.limitsVisible

                ColumnLayout {
                    id: limitsColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    spacing: 6
                    HusText { text: t.limits || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 4
                        columnSpacing: 10
                        rowSpacing: 4
                        HusText { text: t.group || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        HusText { text: t.pool || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        HusText { text: t.minimum || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        HusText { text: t.maximum || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        Repeater {
                            model: vmGodRoll.groupLimitRows
                            delegate: RowLayout {
                                Layout.columnSpan: 4
                                spacing: 10
                                HusText { Layout.fillWidth: true; text: modelData.label; color: HusTheme.Primary.colorTextBase }
                                HusText { Layout.preferredWidth: 40; text: String(modelData.pool); color: HusTheme.Primary.colorTextSecondary }
                                HusInputInteger {
                                    Layout.preferredWidth: 90
                                    min: 0
                                    max: modelData.hardMax
                                    value: modelData.minimum
                                    onValueModified: vmGodRoll.setGroupLimit(modelData.group, value, Math.max(value, modelData.maximum))
                                }
                                HusInputInteger {
                                    Layout.preferredWidth: 90
                                    min: 0
                                    max: modelData.hardMax
                                    value: modelData.maximum
                                    onValueModified: vmGodRoll.setGroupLimit(modelData.group, Math.min(value, modelData.minimum), value)
                                }
                            }
                        }
                    }
                }
            }

            // ---- 运行 ----
            GlassPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: runGrid.implicitHeight + 28

                GridLayout {
                    id: runGrid
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    columns: 4
                    columnSpacing: 10
                    rowSpacing: 6
                    HusText { text: t.effort || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    HusText { text: t.top_n || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    HusText { text: t.score_profile || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                    HusText { text: ""; }
                    AppSelect {
                        Layout.fillWidth: true
                        model: vmGodRoll.effortOptions
                        currentIndex: vmGodRoll.effortIndex
                        enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                        onActivated: function(index) { vmGodRoll.setEffortIndex(index); }
                    }
                    HusInputInteger {
                        Layout.fillWidth: true
                        min: 1
                        max: 10
                        value: vmGodRoll.topN
                        enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                        onValueModified: vmGodRoll.setTopN(value)
                    }
                    AppSelect {
                        Layout.fillWidth: true
                        model: vmGodRoll.profileOptions
                        currentIndex: vmGodRoll.profileIndex
                        enabled: !vmGodRoll.searching && !vmGodRoll.liveMode
                        onActivated: function(index) { vmGodRoll.setProfileIndex(index); }
                    }
                    RowLayout {
                        spacing: 8
                        HusButton {
                            text: t.search || ""
                            type: HusButton.Type_Primary
                            enabled: vmGodRoll.canSearch
                            onClicked: vmGodRoll.startSearch()
                        }
                        HusButton {
                            text: t.cancel || ""
                            enabled: vmGodRoll.searching
                            onClicked: vmGodRoll.cancelSearch()
                        }
                    }
                    HusText {
                        Layout.columnSpan: 4
                        text: vmGodRoll.statusText
                        color: HusTheme.Primary.colorTextSecondary
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }
    }

    // ================= 结果页 =================
    ColumnLayout {
        anchors.fill: parent
        visible: vmGodRoll.resultsVisible
        spacing: 10

        RowLayout {
            spacing: 10
            HusButton {
                text: "← " + (t.back || "Back")
                onClicked: vmGodRoll.closeResults()
            }
            HusText {
                Layout.fillWidth: true
                text: vmGodRoll.resultsSummary
                color: HusTheme.Primary.colorTextSecondary
                wrapMode: Text.Wrap
            }
            HusButton {
                text: t.add_all || ""
                type: HusButton.Type_Primary
                enabled: appBridge.saveLoaded && vmGodRoll.results.length > 0
                onClicked: {
                    var indices = [];
                    for (var i = 0; i < vmGodRoll.results.length; i++) indices.push(i);
                    vmGodRoll.addResults(indices);
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10

            // 结果列表
            GlassPanel {
                Layout.preferredWidth: 320
                Layout.fillHeight: true

                LockedListView {
                    anchors.fill: parent
                    anchors.margins: 6
                    clip: true
                    spacing: 7
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: HusScrollBar { }
                    model: vmGodRoll.results
                    // 结果卡片（对齐主线 rollResultList::item：边框 + 圆角 + 间距 + 选中强调，
                    // 不再整行铺稀有度底色——深色下那是片看不清的屎黄）
                    delegate: Item {
                        id: resultDelegate
                        width: ListView.view.width
                        height: rowColumn.implicitHeight + 20
                        property bool selected: vmGodRoll.resultIndex === index
                        Rectangle {
                            anchors.fill: parent
                            radius: 8
                            color: resultDelegate.selected ? selStyle.bg
                                 : resultHover.containsMouse ? (HusTheme.isDark ? "#1AFFFFFF" : "#0D000000")
                                 : "transparent"
                            border.color: resultDelegate.selected ? HusTheme.Primary.colorPrimary
                                 : resultHover.containsMouse ? HusTheme.Primary.colorPrimary
                                 : selStyle.cardBorder
                            border.width: 1
                        }
                        // 左侧稀有度色条（替代整行屎黄底色）
                        Rectangle {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            anchors.margins: 3
                            width: 3
                            radius: 2
                            color: modelData.rarity_color || "transparent"
                        }
                        Column {
                            id: rowColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 14
                            anchors.rightMargin: 10
                            spacing: 2
                            HusText {
                                width: parent.width
                                text: modelData.name
                                color: resultDelegate.selected ? selStyle.text : HusTheme.Primary.colorTextBase
                                elide: Text.ElideRight
                            }
                            HusText {
                                width: parent.width
                                text: modelData.meta_text || ""
                                color: resultDelegate.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                            HusText {
                                width: parent.width
                                text: modelData.stats_text || ""
                                color: resultDelegate.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                            HusText {
                                width: parent.width
                                visible: (modelData.score_text || "") !== ""
                                text: modelData.score_text || ""
                                color: resultDelegate.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                            HusText {
                                width: parent.width
                                visible: (modelData.variant_summary || "") !== ""
                                text: modelData.variant_summary || ""
                                color: resultDelegate.selected ? selStyle.tertiaryText : HusTheme.Primary.colorTextTertiary
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                        }
                        MouseArea {
                            id: resultHover
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: vmGodRoll.setResultIndex(index)
                        }
                    }
                }
            }

            // 详情
            GlassPanel {
                Layout.fillWidth: true
                Layout.fillHeight: true

                LockedFlickable {
                    anchors.fill: parent
                    contentWidth: width
                    contentHeight: detailColumn.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: HusScrollBar { }

                    ColumnLayout {
                        id: detailColumn
                        width: parent.width - 2
                        spacing: 8

                        RowLayout {
                            spacing: 8
                            HusText {
                                Layout.fillWidth: true
                                text: vmGodRoll.currentResult.name || "—"
                                font.bold: true
                                font.pixelSize: 15
                                color: HusTheme.Primary.colorTextBase
                                elide: Text.ElideRight
                            }
                            HusTag {
                                text: vmGodRoll.currentResult.rarity || ""
                                // 稀有度本色（HusTag 自定义色），不再用深色的屎黄 gold
                                presetColor: vmGodRoll.currentResult.rarity_color || "#c8871e"
                            }
                            HusTag {
                                text: vmGodRoll.currentResult.status_label || ""
                                presetColor: vmGodRoll.currentResult.status === "legal" ? "green" : "orange"
                            }
                        }
                        HusText {
                            text: (vmGodRoll.currentResult.manufacturer || "") + " · "
                                  + (vmGodRoll.currentResult.weapon_type || "")
                                  + (vmGodRoll.currentResult.element ? " · " + vmGodRoll.currentResult.element : "")
                            color: HusTheme.Primary.colorTextSecondary
                        }
                        RowLayout {
                            spacing: 8
                            HusButton {
                                text: t.add_one || ""
                                type: HusButton.Type_Primary
                                enabled: appBridge.saveLoaded
                                onClicked: vmGodRoll.addResults([vmGodRoll.resultIndex])
                            }
                            HusButton {
                                text: t.copy_base85 || ""
                                onClicked: vmGodRoll.copyResult(vmGodRoll.resultIndex)
                            }
                            HusButton {
                                text: t.open_editor || ""
                                onClicked: vmGodRoll.openInEditor(vmGodRoll.resultIndex)
                            }
                        }
                        RowLayout {
                            spacing: 12
                            Repeater {
                                model: vmGodRoll.currentResult.formatted_stats || []
                                delegate: HusText {
                                    text: modelData.label + ": " + modelData.value
                                    color: HusTheme.Primary.colorTextBase
                                    font.pixelSize: 11
                                }
                            }
                        }
                        // 带图标的技能展示（与物品页武器卡同一图标资源）
                        HusDivider { Layout.fillWidth: true; visible: effectRepeater.count > 0 }
                        HusText {
                            visible: effectRepeater.count > 0
                            text: t.effects_title || "Skills"
                            font.bold: true
                            color: HusTheme.Primary.colorTextBase
                        }
                        Repeater {
                            id: effectRepeater
                            model: vmGodRoll.currentResult.effect_entries || []
                            delegate: Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: effectRow.implicitHeight + 12
                                radius: 6
                                color: HusTheme.isDark ? "#22FFFFFF" : "#11000000"
                                RowLayout {
                                    id: effectRow
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 6
                                    spacing: 8
                                    Rectangle {
                                        visible: (modelData.icon || "") !== ""
                                        Layout.preferredWidth: 30
                                        Layout.preferredHeight: 30
                                        Layout.alignment: Qt.AlignTop
                                        radius: 4
                                        color: "#164653"
                                        Image {
                                            anchors.centerIn: parent
                                            source: modelData.icon || ""
                                            sourceSize.width: 26
                                            sourceSize.height: 26
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        HusText {
                                            text: modelData.title
                                            font.bold: true
                                            color: "#39BCE8"
                                            wrapMode: Text.Wrap
                                            Layout.fillWidth: true
                                        }
                                        HusText {
                                            visible: (modelData.description || "") !== ""
                                            text: modelData.description
                                            color: HusTheme.Primary.colorTextSecondary
                                            font.pixelSize: 11
                                            wrapMode: Text.Wrap
                                            Layout.fillWidth: true
                                        }
                                    }
                                }
                            }
                        }
                        HusDivider { Layout.fillWidth: true }
                        HusText { text: t.score_explanation || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                        HusText {
                            text: vmGodRoll.currentScoreText
                            color: HusTheme.Primary.colorTextSecondary
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                        HusDivider { Layout.fillWidth: true }
                        HusText { text: t.parts_title || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                        Repeater {
                            model: vmGodRoll.currentPartDetails
                            delegate: Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: partCol.implicitHeight + 14
                                radius: 6
                                color: HusTheme.isDark ? "#22FFFFFF" : "#11000000"
                                ColumnLayout {
                                    id: partCol
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 7
                                    spacing: 2
                                    HusText {
                                        text: (index + 1) + ". " + (modelData.name === modelData.group_label
                                              ? modelData.group_label : modelData.group_label + " · " + modelData.name)
                                        font.bold: true
                                        color: HusTheme.Primary.colorTextBase
                                        wrapMode: Text.Wrap
                                        Layout.fillWidth: true
                                    }
                                    HusText {
                                        text: [modelData.ref, modelData.source_label].filter(function(s){ return s !== ""; }).join(" · ")
                                        color: HusTheme.Primary.colorTextTertiary
                                        font.pixelSize: 11
                                        wrapMode: Text.Wrap
                                        Layout.fillWidth: true
                                    }
                                    HusText {
                                        text: modelData.description
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
        }
    }
}
