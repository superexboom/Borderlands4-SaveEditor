import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "../components"

// 技能树页：在线读取当前角色的技能，按游戏技能界面的样式编辑（三棵树 + 专精），
// 再一次性应用到游戏（skill_apply，由游戏自己校验点数与前置条件）。
Item {
    id: page
    objectName: "skillTreePage"

    readonly property var loc: vmSkillTree.strings
    readonly property int rev: vmSkillTree.revision
    readonly property var trees: vmSkillTree.trees
    readonly property var sel: vmSkillTree.selected
    property int treeIndex: 0          // 0..2 = 技能树，3 = 专精
    property int bonusValue: 5

    function kindLabel(kind) {
        return (page.loc["kind_" + kind] || "");
    }

    EmptyHint {
        anchors.fill: parent
        visible: !vmSkillTree.liveMode || !vmSkillTree.loaded
        description: !vmSkillTree.liveMode ? (page.loc.live_required || "") : (page.loc.read_hint || "")
    }
    HusButton {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: 60
        visible: vmSkillTree.liveMode && !vmSkillTree.loaded
        type: HusButton.Type_Primary
        text: page.loc.read || ""
        enabled: !vmSkillTree.busy
        onClicked: vmSkillTree.load()
    }

    ColumnLayout {
        anchors.fill: parent
        visible: vmSkillTree.liveMode && vmSkillTree.loaded
        spacing: 10

        // ---- 工具栏 ----
        GlassPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: toolbar.implicitHeight + 20

            ColumnLayout {
                id: toolbar
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 10
                spacing: 8
                RowLayout {
                    spacing: 10
                    HusText {
                        text: vmSkillTree.className
                        font.bold: true
                        font.pixelSize: 16
                        color: HusTheme.Primary.colorTextBase
                    }
                    HusText {
                        Layout.fillWidth: true
                        text: vmSkillTree.summary
                        color: vmSkillTree.overBudget ? "#e05a4f" : HusTheme.Primary.colorTextSecondary
                        elide: Text.ElideRight
                    }
                    HusButton {
                        text: page.loc.reload || ""
                        enabled: !vmSkillTree.busy
                        onClicked: vmSkillTree.load()
                    }
                    HusButton {
                        text: page.loc.revert || ""
                        enabled: vmSkillTree.dirty && !vmSkillTree.busy
                        onClicked: vmSkillTree.bulk("revert")
                    }
                    HusButton {
                        objectName: "skillApply"
                        type: HusButton.Type_Primary
                        text: page.loc.apply || ""
                        enabled: vmSkillTree.dirty && !vmSkillTree.busy
                        onClicked: vmSkillTree.apply()
                    }
                }
                RowLayout {
                    spacing: 8
                    HusButton {
                        text: page.loc.max_trees || ""
                        onClicked: vmSkillTree.bulk("max_trees")
                    }
                    HusButton {
                        text: page.loc.clear_points || ""
                        onClicked: vmSkillTree.bulk("clear_points")
                    }
                    Rectangle { width: 1; height: 24; color: HusTheme.Primary.colorTextQuaternary }
                    HusText {
                        text: page.loc.bonus_invested || ""
                        color: HusTheme.Primary.colorTextSecondary
                    }
                    CountStepper {
                        value: page.bonusValue
                        min: 0
                        max: 99
                        onStepped: function(delta) { page.bonusValue = Math.max(0, Math.min(99, page.bonusValue + delta)); }
                        onValueCommitted: function(v) { page.bonusValue = v; }
                    }
                    HusButton {
                        text: page.loc.bonus_set || ""
                        onClicked: vmSkillTree.bonusInvested(page.bonusValue)
                    }
                    HusButton {
                        text: page.loc.clear_bonus || ""
                        onClicked: vmSkillTree.bulk("clear_bonus")
                    }
                    Item { Layout.fillWidth: true }
                    HusText {
                        text: page.loc.mouse_hint || ""
                        font.pixelSize: 12
                        color: HusTheme.Primary.colorTextTertiary
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10

            // ---- 树 ----
            GlassPanel {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 8

                    RowLayout {
                        spacing: 6
                        Repeater {
                            model: page.trees
                            delegate: HusButton {
                                required property var modelData
                                required property int index
                                text: modelData.name + (modelData.action.name ? " · " + modelData.action.name : "")
                                type: page.treeIndex === index ? HusButton.Type_Primary : HusButton.Type_Default
                                onClicked: page.treeIndex = index
                                // 树的颜色（游戏里绿 / 蓝 / 红）
                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    anchors.margins: 3
                                    height: 3
                                    radius: 1.5
                                    color: modelData.color
                                }
                            }
                        }
                        HusButton {
                            text: page.loc.specializations || ""
                            type: page.treeIndex === 3 ? HusButton.Type_Primary : HusButton.Type_Default
                            onClicked: page.treeIndex = 3
                        }
                    }

                    LockedFlickable {
                        id: treeFlick
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: Math.max(width, treeContent.implicitWidth)
                        contentHeight: Math.max(height, treeContent.implicitHeight)
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: HusScrollBar { }
                        ScrollBar.horizontal: HusScrollBar { }

                        Item {
                            id: treeContent
                            width: treeFlick.contentWidth
                            height: treeFlick.contentHeight
                            implicitWidth: page.treeIndex < 3 ? treeView.implicitWidth : specView.implicitWidth
                            implicitHeight: page.treeIndex < 3 ? treeView.implicitHeight : specView.implicitHeight

                            // 一棵树：分支在上（三个 3×3 并排），主干在下（3×5），最底下是动作技能
                            ColumnLayout {
                                id: treeView
                                visible: page.treeIndex < 3 && page.treeIndex < page.trees.length
                                anchors.horizontalCenter: parent.horizontalCenter
                                spacing: 18
                                readonly property var tree: page.trees[Math.min(page.treeIndex, page.trees.length - 1)] || ({})

                                RowLayout {
                                    Layout.alignment: Qt.AlignHCenter
                                    spacing: 26
                                    Repeater {
                                        model: treeView.tree.branches || []
                                        delegate: SegmentGrid { segment: modelData; columns: 3 }
                                    }
                                }
                                Rectangle {
                                    Layout.alignment: Qt.AlignHCenter
                                    Layout.preferredWidth: trunkGrid.implicitWidth
                                    Layout.preferredHeight: 2
                                    color: treeView.tree.color || "#888888"
                                    opacity: 0.5
                                }
                                SegmentGrid {
                                    id: trunkGrid
                                    Layout.alignment: Qt.AlignHCenter
                                    segment: treeView.tree.trunk || ({})
                                    columns: 5
                                }
                                ColumnLayout {
                                    Layout.alignment: Qt.AlignHCenter
                                    spacing: 2
                                    SkillCell {
                                        Layout.alignment: Qt.AlignHCenter
                                        cell: treeView.tree.action || ({})
                                        vm: vmSkillTree
                                        revision: page.rev
                                        size: 84
                                    }
                                    HusText {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: (treeView.tree.action || {}).name || ""
                                        font.bold: true
                                        color: treeView.tree.color || HusTheme.Primary.colorTextBase
                                    }
                                }
                            }

                            // 专精：每棵专精一行，点数 + 三个专精技能
                            ColumnLayout {
                                id: specView
                                visible: page.treeIndex === 3
                                anchors.horizontalCenter: parent.horizontalCenter
                                spacing: 10
                                HusText {
                                    text: vmSkillTree.specSlotsText
                                    color: HusTheme.Primary.colorTextSecondary
                                }
                                Repeater {
                                    model: vmSkillTree.specs
                                    delegate: RowLayout {
                                        required property var modelData
                                        spacing: 12
                                        HusText {
                                            Layout.preferredWidth: 140
                                            text: modelData.name
                                            font.bold: true
                                            color: HusTheme.Primary.colorTextBase
                                            MouseArea {
                                                anchors.fill: parent
                                                onClicked: vmSkillTree.select(modelData.graph, modelData.i)
                                            }
                                        }
                                        CountStepper {
                                            value: { page.rev; return vmSkillTree.value(modelData.graph, modelData.i, "spent"); }
                                            min: 0
                                            max: modelData.max
                                            onStepped: function(delta) { vmSkillTree.step(modelData.graph, modelData.i, "spent", delta); }
                                            onValueCommitted: function(v) { vmSkillTree.setValue(modelData.graph, modelData.i, "spent", v); }
                                        }
                                        Repeater {
                                            model: modelData.skills
                                            delegate: ColumnLayout {
                                                required property var modelData
                                                spacing: 2
                                                SkillCell {
                                                    Layout.alignment: Qt.AlignHCenter
                                                    cell: modelData
                                                    vm: vmSkillTree
                                                    revision: page.rev
                                                    size: 60
                                                }
                                                HusText {
                                                    Layout.preferredWidth: 110
                                                    horizontalAlignment: Text.AlignHCenter
                                                    text: modelData.name
                                                    font.pixelSize: 12
                                                    elide: Text.ElideRight
                                                    color: HusTheme.Primary.colorTextSecondary
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

            // ---- 详情 ----
            GlassPanel {
                Layout.preferredWidth: 320
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10
                    HusText {
                        Layout.fillWidth: true
                        visible: !page.sel.graph
                        text: page.loc.select_hint || ""
                        color: HusTheme.Primary.colorTextTertiary
                        wrapMode: Text.Wrap
                    }
                    HusText {
                        Layout.fillWidth: true
                        visible: !!page.sel.graph
                        text: page.sel.name || ""
                        font.bold: true
                        font.pixelSize: 16
                        color: page.sel.color || HusTheme.Primary.colorTextBase
                        wrapMode: Text.Wrap
                    }
                    HusText {
                        visible: !!page.sel.graph
                        text: page.kindLabel(page.sel.kind)
                        font.pixelSize: 12
                        color: HusTheme.Primary.colorTextTertiary
                    }
                    GridLayout {
                        visible: page.sel.kind === "passive" || page.sel.kind === "spec"
                        columns: 2
                        columnSpacing: 10
                        rowSpacing: 6
                        HusText { text: page.loc.points || ""; color: HusTheme.Primary.colorTextSecondary }
                        CountStepper {
                            value: { page.rev; return page.sel.graph ? vmSkillTree.value(page.sel.graph, page.sel.i, "spent") : 0; }
                            min: 0
                            max: page.sel.max || 0
                            onStepped: function(delta) { vmSkillTree.step(page.sel.graph, page.sel.i, "spent", delta); }
                            onValueCommitted: function(v) { vmSkillTree.setValue(page.sel.graph, page.sel.i, "spent", v); }
                        }
                        HusText { text: page.loc.bonus || ""; color: "#e67e22" }
                        CountStepper {
                            value: { page.rev; return page.sel.graph ? vmSkillTree.value(page.sel.graph, page.sel.i, "bonus") : 0; }
                            min: 0
                            max: 99
                            onStepped: function(delta) { vmSkillTree.step(page.sel.graph, page.sel.i, "bonus", delta); }
                            onValueCommitted: function(v) { vmSkillTree.setValue(page.sel.graph, page.sel.i, "bonus", v); }
                        }
                    }
                    HusButton {
                        readonly property bool isActive: { page.rev; return page.sel.graph ? vmSkillTree.value(page.sel.graph, page.sel.i, "active") === 1 : false; }
                        visible: page.sel.kind === "augment" || page.sel.kind === "capstone"
                                 || page.sel.kind === "action" || page.sel.kind === "perk"
                        type: isActive ? HusButton.Type_Primary : HusButton.Type_Default
                        text: isActive ? (page.loc.active_on || "") : (page.loc.active_off || "")
                        onClicked: vmSkillTree.toggle(page.sel.graph, page.sel.i)
                    }
                    LockedFlickable {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: width
                        contentHeight: descText.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: HusScrollBar { }
                        Text {
                            id: descText
                            width: parent.width - 4
                            text: HoverTip.themeHtml(page.sel.descHtml || "")
                            textFormat: Text.RichText
                            wrapMode: Text.Wrap
                            font.family: "Microsoft YaHei UI"
                            font.pixelSize: 13
                            color: HusTheme.Primary.colorTextBase
                        }
                    }
                }
            }
        }
    }

    // 一个 progress graph 段（主干 / 分支）：rows 已按游戏样式从上到下排好
    component SegmentGrid: GridLayout {
        id: grid
        property var segment: ({})
        rowSpacing: 6
        columnSpacing: 6
        Repeater {
            model: {
                var out = [];
                var rows = (grid.segment || {}).rows || [];
                for (var r = 0; r < rows.length; r++)
                    for (var c = 0; c < rows[r].length; c++) out.push(rows[r][c]);
                return out;
            }
            delegate: SkillCell {
                cell: modelData
                vm: vmSkillTree
                revision: page.rev
            }
        }
    }
}
