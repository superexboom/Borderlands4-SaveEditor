// 游戏进度 · 任务：左侧按本体/DLC × 主线/支线/小任务/区域活动分类，右侧逐个任务完成或重置。
// 主线保持剧情顺序（「完成至此」会一并完成前置主线，且不提供重置）；其余按区域分组。
// 点击任务行展开描述与目标（进行中的任务显示存档里每个目标的状态）。
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic

RowLayout {
    id: tab
    property var labels: ({})
    property var buttons: ({})
    property int filterMode: 0   // 0 全部 / 1 已完成 / 2 进行中 / 3 未开始
    property string search: ""
    property string expandedKey: ""
    spacing: 10

    readonly property color doneColor: "#78dba9"
    readonly property color activeColor: "#4a90e2"
    readonly property var stateFilter: ["", "done", "active", "none"]

    readonly property bool mainCategory: vmGameProgress.missionCategory.split(":")[1] === "main"
    // 先绑定到 var 属性再遍历：直接在 JS 里遍历 VM 的列表属性，每访问一个元素都会重新读取整个列表
    readonly property var sourceRows: vmGameProgress.missionRows
    readonly property var rows: {
        var source = sourceRows, out = [], last = null;
        var needle = search.trim().toLowerCase(), wanted = stateFilter[filterMode];
        for (var i = 0; i < source.length; i++) {
            var row = source[i];
            if (wanted && row.state !== wanted) continue;
            if (needle && (row.title + " " + row.desc + " " + row.group).toLowerCase().indexOf(needle) < 0) continue;
            if (row.group && row.group !== last) {
                out.push({ header: true, title: row.group });
                last = row.group;
            }
            out.push(row);
        }
        return out;
    }

    function stateText(state) {
        if (state === "done") return labels.mission_done || "";
        if (state === "active") return labels.mission_active || "";
        return labels.mission_none || "";
    }
    function stateColor(state) {
        if (state === "done") return doneColor;
        if (state === "active") return activeColor;
        return HusTheme.Primary.colorTextTertiary;
    }
    function objectiveGlyph(state) {
        if (state === "done") return "✓";
        if (state === "skipped") return "–";
        if (state === "active") return "●";
        return "○";
    }

    Component.onCompleted: {
        if (!vmGameProgress.missionCategory && vmGameProgress.missionCategories.length)
            vmGameProgress.setMissionCategory(vmGameProgress.missionCategories[0].key);
    }

    GlassPanel {
        Layout.preferredWidth: 250
        Layout.fillHeight: true
        ProgressCategoryList {
            anchors.fill: parent
            anchors.margins: 6
            categories: vmGameProgress.missionCategories
            current: vmGameProgress.missionCategory
            groupField: "area"
            onPicked: function(key) { tab.expandedKey = ""; vmGameProgress.setMissionCategory(key); }
        }
    }

    GlassPanel {
        Layout.fillWidth: true
        Layout.fillHeight: true

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                HusInput {
                    Layout.preferredWidth: 220
                    placeholderText: tab.labels.search || ""
                    onTextChanged: tab.search = text
                }
                Repeater {
                    model: [tab.labels.filter_all || "All", tab.labels.filter_done || "Done",
                            tab.labels.filter_active || "In progress", tab.labels.filter_none || "Not started"]
                    delegate: HusButton {
                        text: modelData
                        type: tab.filterMode === index ? HusButton.Type_Primary : HusButton.Type_Default
                        onClicked: tab.filterMode = index
                    }
                }
                Item { Layout.fillWidth: true }
                HusButton {
                    text: tab.buttons.complete_all || ""
                    enabled: vmGameProgress.editable && vmGameProgress.missionCategory !== ""
                    onClicked: vmGameProgress.completeMissionCategory()
                }
                HusButton {
                    visible: !tab.mainCategory
                    text: tab.buttons.reset_all || ""
                    enabled: vmGameProgress.editable && vmGameProgress.missionCategory !== ""
                    onClicked: vmGameProgress.resetMissionCategory()
                }
            }

            HusText {
                Layout.fillWidth: true
                text: tab.labels.rewards_note || ""
                font.pixelSize: 12
                color: HusTheme.Primary.colorTextTertiary
                wrapMode: Text.Wrap
            }

            LockedListView {
                objectName: "missionList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 4
                ScrollBar.vertical: HusScrollBar { }
                model: tab.rows

                delegate: Item {
                    id: rowItem
                    readonly property bool expanded: !modelData.header && tab.expandedKey === modelData.key
                    width: ListView.view.width - 10
                    height: modelData.header ? 30 : card.height

                    HusText {
                        visible: !!modelData.header
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 4
                        text: modelData.title || ""
                        font.bold: true
                        color: HusTheme.Primary.colorTextTertiary
                    }

                    Rectangle {
                        id: card
                        visible: !modelData.header
                        width: parent.width
                        height: body.implicitHeight + 16
                        radius: 8
                        color: rowArea.containsMouse || rowItem.expanded
                               ? (HusTheme.isDark ? "#1cffffff" : "#12000000")
                               : (HusTheme.isDark ? "#14ffffff" : "#0c000000")

                        MouseArea {
                            id: rowArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: tab.expandedKey = rowItem.expanded ? "" : modelData.key
                        }

                        ColumnLayout {
                            id: body
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 8
                            anchors.leftMargin: 12
                            anchors.rightMargin: 10
                            spacing: 6

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10

                                Rectangle {
                                    Layout.preferredWidth: stateLabel.implicitWidth + 16
                                    Layout.preferredHeight: 22
                                    radius: 11
                                    color: "transparent"
                                    border.width: 1
                                    border.color: tab.stateColor(modelData.state)
                                    HusText {
                                        id: stateLabel
                                        anchors.centerIn: parent
                                        text: tab.stateText(modelData.state)
                                        font.pixelSize: 12
                                        color: tab.stateColor(modelData.state)
                                    }
                                }
                                HusText {
                                    Layout.fillWidth: true
                                    text: modelData.title || ""
                                    font.bold: true
                                    elide: Text.ElideRight
                                }
                                HusText {
                                    visible: modelData.state === "active" && (modelData.objectives || []).length > 0
                                    text: (tab.labels.objectives || "{done}/{total}")
                                          .replace("{done}", modelData.objectives_done)
                                          .replace("{total}", (modelData.objectives || []).length)
                                    font.pixelSize: 12
                                    color: tab.activeColor
                                }
                                HusText {
                                    visible: modelData.prerequisites > 0
                                    text: (tab.labels.prerequisites || "").replace("{count}", modelData.prerequisites)
                                    font.pixelSize: 12
                                    color: "#e6a439"
                                }
                                Rectangle {
                                    id: minimalTag
                                    visible: !modelData.template && modelData.state !== "done"
                                    Layout.preferredWidth: minimalText.implicitWidth + 12
                                    Layout.preferredHeight: 20
                                    radius: 4
                                    color: HusTheme.isDark ? "#26e6a439" : "#1ae6a439"
                                    HusText {
                                        id: minimalText
                                        anchors.centerIn: parent
                                        text: tab.labels.no_template || ""
                                        font.pixelSize: 11
                                        color: "#e6a439"
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        onContainsMouseChanged: containsMouse
                                            ? HoverTip.showFor(minimalTag, tab.labels.no_template_tip || "", mouseX, mouseY)
                                            : HoverTip.hideFor(minimalTag)
                                    }
                                    Component.onDestruction: HoverTip.hideFor(minimalTag)
                                }
                                HusButton {
                                    visible: modelData.state !== "done"
                                    enabled: vmGameProgress.editable
                                    type: HusButton.Type_Primary
                                    text: modelData.prerequisites > 0 ? (tab.buttons.complete_through || "")
                                                                      : (tab.buttons.complete_mission || "")
                                    onClicked: vmGameProgress.completeMission(modelData.key)
                                }
                                HusButton {
                                    visible: !!modelData.can_reset
                                    enabled: vmGameProgress.editable
                                    text: tab.buttons.reset_mission || ""
                                    onClicked: vmGameProgress.resetMission(modelData.key)
                                }
                            }

                            HusText {
                                Layout.fillWidth: true
                                visible: !!modelData.desc
                                text: modelData.desc || ""
                                font.pixelSize: 12
                                color: HusTheme.Primary.colorTextSecondary
                                wrapMode: rowItem.expanded ? Text.Wrap : Text.NoWrap
                                elide: rowItem.expanded ? Text.ElideNone : Text.ElideRight
                                maximumLineCount: rowItem.expanded ? 12 : 1
                            }

                            // 展开：进行中任务的目标状态（✓ 完成 · ● 进行中 · – 已跳过 · ○ 未到达）
                            Column {
                                Layout.fillWidth: true
                                visible: rowItem.expanded && (modelData.objectives || []).length > 0
                                spacing: 3
                                Repeater {
                                    model: rowItem.expanded ? modelData.objectives : []
                                    delegate: Row {
                                        spacing: 8
                                        leftPadding: modelData.child ? 22 : 4
                                        HusText {
                                            width: 14
                                            text: tab.objectiveGlyph(modelData.state)
                                            color: modelData.state === "done" ? tab.doneColor
                                                 : modelData.state === "active" ? tab.activeColor
                                                 : HusTheme.Primary.colorTextTertiary
                                        }
                                        HusText {
                                            text: modelData.text
                                            font.pixelSize: 12
                                            font.strikeout: modelData.state === "skipped"
                                            color: modelData.state === "active" ? HusTheme.Primary.colorTextBase
                                                                               : HusTheme.Primary.colorTextSecondary
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
}
