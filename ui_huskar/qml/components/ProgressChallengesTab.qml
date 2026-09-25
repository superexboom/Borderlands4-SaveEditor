// 游戏进度 · 挑战与成就：左侧游戏内挑战菜单分类（+成就），右侧逐项查看与编辑。
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic

RowLayout {
    id: tab
    property var labels: ({})
    property var buttons: ({})
    property int filterMode: 0   // 0 全部 / 1 已完成 / 2 未完成
    property string search: ""
    spacing: 10

    readonly property var rows: {
        var source = vmGameProgress.challengeRows, out = [], needle = search.trim().toLowerCase();
        for (var i = 0; i < source.length; i++) {
            var row = source[i];
            if (filterMode === 1 && !row.done) continue;
            if (filterMode === 2 && row.done) continue;
            if (needle && (row.title + " " + row.desc).toLowerCase().indexOf(needle) < 0) continue;
            out.push(row);
        }
        return out;
    }

    Component.onCompleted: {
        if (!vmGameProgress.challengeCategory && vmGameProgress.challengeCategories.length)
            vmGameProgress.setChallengeCategory(vmGameProgress.challengeCategories[0].key);
    }

    GlassPanel {
        Layout.preferredWidth: 250
        Layout.fillHeight: true
        ProgressCategoryList {
            anchors.fill: parent
            anchors.margins: 6
            categories: vmGameProgress.challengeCategories
            current: vmGameProgress.challengeCategory
            onPicked: function(key) { vmGameProgress.setChallengeCategory(key); }
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
                    model: [tab.labels.filter_all || "All", tab.labels.filter_done || "Done", tab.labels.filter_todo || "Not done"]
                    delegate: HusButton {
                        text: modelData
                        type: tab.filterMode === index ? HusButton.Type_Primary : HusButton.Type_Default
                        onClicked: tab.filterMode = index
                    }
                }
                Item { Layout.fillWidth: true }
                HusButton {
                    text: tab.buttons.complete_all || ""
                    enabled: vmGameProgress.editable && vmGameProgress.challengeCategory !== ""
                    onClicked: vmGameProgress.completeChallengeCategory(true)
                }
                HusButton {
                    text: tab.buttons.reset_all || ""
                    enabled: vmGameProgress.editable && vmGameProgress.challengeCategory !== ""
                    onClicked: vmGameProgress.completeChallengeCategory(false)
                }
            }

            LockedListView {
                id: challengeList
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 6
                ScrollBar.vertical: HusScrollBar { }
                model: tab.rows
                delegate: Rectangle {
                    width: ListView.view.width - 10
                    height: body.implicitHeight + 18
                    radius: 8
                    color: HusTheme.isDark ? "#14ffffff" : "#0c000000"
                    border.width: modelData.done ? 1 : 0
                    border.color: "#5578dba9"

                    RowLayout {
                        id: body
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 12

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3
                            RowLayout {
                                spacing: 6
                                HusText {
                                    text: modelData.done ? "✓" : ""
                                    visible: modelData.done
                                    color: "#78dba9"
                                    font.bold: true
                                }
                                HusText {
                                    Layout.fillWidth: true
                                    text: modelData.title
                                    font.bold: true
                                    color: HusTheme.Primary.colorTextBase
                                    elide: Text.ElideRight
                                }
                            }
                            HusText {
                                Layout.fillWidth: true
                                visible: text !== ""
                                text: modelData.desc
                                color: HusTheme.Primary.colorTextSecondary
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.maximumWidth: 360
                                    height: 4
                                    radius: 2
                                    color: HusTheme.isDark ? "#22ffffff" : "#18000000"
                                    Rectangle {
                                        width: modelData.goal > 0 ? parent.width * Math.min(1, modelData.value / modelData.goal) : 0
                                        height: parent.height
                                        radius: 2
                                        color: modelData.done ? "#78dba9" : "#4a90e2"
                                    }
                                }
                                HusText {
                                    text: modelData.value + " / " + modelData.goal
                                          + (modelData.tiers ? "   (" + modelData.tiers + ")" : "")
                                          + (modelData.aggregate ? "   · " + (tab.labels.aggregate || "") : "")
                                    color: HusTheme.Primary.colorTextTertiary
                                    font.pixelSize: 12
                                }
                            }
                        }

                        HusInput {
                            visible: !modelData.aggregate
                            Layout.preferredWidth: 96
                            text: String(modelData.value)
                            enabled: vmGameProgress.editable
                            validator: IntValidator { bottom: 0; top: 2147483647 }
                            onEditingFinished: vmGameProgress.setChallengeValue(modelData.key, text)
                        }
                        HusButton {
                            text: tab.buttons.complete || ""
                            enabled: vmGameProgress.editable && !modelData.done
                            onClicked: vmGameProgress.completeChallenge(modelData.key, true)
                        }
                        HusButton {
                            text: tab.buttons.reset || ""
                            enabled: vmGameProgress.editable && modelData.value > 0
                            onClicked: vmGameProgress.completeChallenge(modelData.key, false)
                        }
                    }
                }
            }
        }
    }
}
