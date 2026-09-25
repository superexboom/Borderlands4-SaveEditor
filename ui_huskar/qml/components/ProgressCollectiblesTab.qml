// 游戏进度 · 收集与探索：左侧按本体/DLC 分组的收集品类别，右侧按区域分组逐项勾选。
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic

RowLayout {
    id: tab
    property var labels: ({})
    property var buttons: ({})
    property int filterMode: 0   // 0 全部 / 1 已收集 / 2 未收集
    property string search: ""
    // 地图页签就绪后由页面置 true，才显示逐项的「地图」按钮
    property bool mapAvailable: false
    signal showOnMap(string stat)
    spacing: 10

    // 先绑定到 var 属性再遍历：直接在 JS 里遍历 VM 的列表属性，每访问一个元素都会重新读取整个列表
    readonly property var sourceRows: vmGameProgress.collectibleRows
    readonly property var rows: {
        var source = sourceRows, out = [], last = null;
        var needle = search.trim().toLowerCase();
        for (var i = 0; i < source.length; i++) {
            var row = source[i];
            if (filterMode === 1 && !row.collected) continue;
            if (filterMode === 2 && row.collected) continue;
            if (needle && (row.title + " " + row.group + " " + row.location_text).toLowerCase().indexOf(needle) < 0) continue;
            if (row.group !== last) {
                out.push({ header: true, title: row.group });
                last = row.group;
            }
            out.push(row);
        }
        return out;
    }

    Component.onCompleted: {
        if (!vmGameProgress.collectibleCategory && vmGameProgress.collectibleCategories.length)
            vmGameProgress.setCollectibleCategory(vmGameProgress.collectibleCategories[0].key);
    }

    GlassPanel {
        Layout.preferredWidth: 250
        Layout.fillHeight: true
        ProgressCategoryList {
            anchors.fill: parent
            anchors.margins: 6
            categories: vmGameProgress.collectibleCategories
            current: vmGameProgress.collectibleCategory
            groupField: "area"
            onPicked: function(key) { vmGameProgress.setCollectibleCategory(key); }
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
                    model: [tab.labels.filter_all || "All", tab.labels.collected || "Collected", tab.labels.missing || "Missing"]
                    delegate: HusButton {
                        text: modelData
                        type: tab.filterMode === index ? HusButton.Type_Primary : HusButton.Type_Default
                        onClicked: tab.filterMode = index
                    }
                }
                Item { Layout.fillWidth: true }
                HusButton {
                    text: tab.buttons.collect_all || ""
                    enabled: (vmGameProgress.editable || vmGameProgress.liveCollect) && vmGameProgress.collectibleCategory !== ""
                    onClicked: vmGameProgress.setCategoryCollected(true)
                }
                HusButton {
                    // 联机时只能收集（游戏没有「取消收集」）
                    visible: !vmGameProgress.liveMode
                    text: tab.buttons.uncollect_all || ""
                    enabled: vmGameProgress.editable && vmGameProgress.collectibleCategory !== ""
                    onClicked: vmGameProgress.setCategoryCollected(false)
                }
            }
            HusText {
                Layout.fillWidth: true
                visible: vmGameProgress.liveCollect
                text: tab.labels.live_collect_note || ""
                font.pixelSize: 12
                color: "#e6a439"
                wrapMode: Text.Wrap
            }

            LockedListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 4
                ScrollBar.vertical: HusScrollBar { }
                model: tab.rows
                delegate: Item {
                    width: ListView.view.width - 10
                    height: modelData.header ? 30 : 44

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
                        visible: !modelData.header
                        anchors.fill: parent
                        radius: 8
                        color: HusTheme.isDark ? "#14ffffff" : "#0c000000"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 10
                            HusCheckBox {
                                checked: !!modelData.collected
                                // 联机：未收集的可以勾选（经游戏自己的挑战计数记入），已收集的不能取消
                                enabled: vmGameProgress.editable || (vmGameProgress.liveCollect && !modelData.collected)
                                onToggled: vmGameProgress.setCollected(modelData.stat, checked)
                            }
                            HusText {
                                Layout.fillWidth: true
                                text: modelData.title || ""
                                color: modelData.collected ? HusTheme.Primary.colorTextBase : "#e6a439"
                                elide: Text.ElideRight
                            }
                            HusText {
                                text: modelData.location_text || ""
                                color: HusTheme.Primary.colorTextTertiary
                                font.pixelSize: 12
                            }
                            HusButton {
                                visible: tab.mapAvailable && !!modelData.on_map
                                text: tab.buttons.show_on_map || "Map"
                                onClicked: tab.showOnMap(modelData.stat)
                            }
                        }
                    }
                }
            }
        }
    }
}
