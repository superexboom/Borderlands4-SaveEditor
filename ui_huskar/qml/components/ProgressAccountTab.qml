// 游戏进度 · 账号进度（profile.sav）：SDU 升级（逐条设等级）、秘藏力量、账号共享解锁与外观台账。
// 左侧分组：账号升级 / 账号共享进度 / 外观；右侧按分类类型切换 SDU、秘藏力量、台账三种视图。
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic

RowLayout {
    id: tab
    property var labels: ({})
    property var buttons: ({})
    property int filterMode: 0   // 0 全部 / 1 已解锁 / 2 未解锁
    property string search: ""
    spacing: 10

    readonly property color doneColor: "#78dba9"
    readonly property string view: vmGameProgress.accountView
    readonly property bool cosmeticLedger: vmGameProgress.accountCategory.indexOf("ledger:unlockable_") === 0

    // 先绑定到 var 属性再遍历：直接在 JS 里遍历 VM 的列表属性，每访问一个元素都会重新读取整个列表
    readonly property var sourceRows: vmGameProgress.accountRows
    readonly property var ledgerRows: {
        if (view !== "ledger") return [];
        var source = sourceRows, out = [], last = null;
        var needle = search.trim().toLowerCase();
        for (var i = 0; i < source.length; i++) {
            var row = source[i];
            if (filterMode === 1 && !row.unlocked) continue;
            if (filterMode === 2 && row.unlocked) continue;
            if (needle && (row.title + " " + row.group + " " + row.entry).toLowerCase().indexOf(needle) < 0) continue;
            if (row.group !== last) {
                out.push({ header: true, title: row.group });
                last = row.group;
            }
            out.push(row);
        }
        return out;
    }

    function fmt(template, values) {
        var text = String(template || "");
        for (var key in values)
            text = text.replace("{" + key + "}", values[key]);
        return text;
    }

    GlassPanel {
        Layout.preferredWidth: 260
        Layout.fillHeight: true
        ProgressCategoryList {
            anchors.fill: parent
            anchors.margins: 6
            categories: vmGameProgress.accountCategories
            current: vmGameProgress.accountCategory
            groupField: "area"
            onPicked: function(key) { tab.search = ""; vmGameProgress.setAccountCategory(key); }
        }
    }

    GlassPanel {
        Layout.fillWidth: true
        Layout.fillHeight: true

        // ---------------- SDU 升级 ----------------
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8
            visible: tab.view === "sdu"

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                HusText {
                    objectName: "sduPoints"
                    text: tab.fmt(tab.labels.sdu_points, vmGameProgress.sduPoints)
                    font.bold: true
                }
                Item { Layout.fillWidth: true }
                HusButton {
                    text: tab.buttons.sdu_max || ""
                    enabled: vmGameProgress.editable
                    onClicked: vmGameProgress.setAllSdu(true)
                }
                HusButton {
                    text: tab.buttons.sdu_clear || ""
                    enabled: vmGameProgress.editable
                    onClicked: vmGameProgress.setAllSdu(false)
                }
            }
            HusText {
                Layout.fillWidth: true
                text: tab.labels.sdu_note || ""
                font.pixelSize: 12
                color: HusTheme.Primary.colorTextTertiary
                wrapMode: Text.Wrap
            }

            LockedListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 6
                ScrollBar.vertical: HusScrollBar { }
                model: tab.view === "sdu" ? tab.sourceRows : []

                delegate: Rectangle {
                    id: sduRow
                    // the segment Repeater below has its own modelData (the index)
                    readonly property var row: modelData
                    width: ListView.view.width - 10
                    height: 68
                    radius: 8
                    color: HusTheme.isDark ? "#14ffffff" : "#0c000000"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 12
                        spacing: 16

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            RowLayout {
                                spacing: 10
                                HusText { text: modelData.title || ""; font.bold: true }
                                HusText {
                                    text: modelData.effect || ""
                                    color: modelData.level >= modelData.max ? tab.doneColor : HusTheme.Primary.colorTextSecondary
                                }
                                HusText {
                                    visible: modelData.level < modelData.max
                                    text: "→ " + (modelData.effect_max || "")
                                    font.pixelSize: 12
                                    color: HusTheme.Primary.colorTextTertiary
                                }
                            }
                            // 等级分段条：已购买的等级填充
                            Row {
                                spacing: 3
                                Repeater {
                                    model: sduRow.row.max
                                    delegate: Rectangle {
                                        width: 26
                                        height: 6
                                        radius: 3
                                        color: index < sduRow.row.level
                                               ? (sduRow.row.level >= sduRow.row.max ? tab.doneColor : "#4a90e2")
                                               : (HusTheme.isDark ? "#22ffffff" : "#18000000")
                                    }
                                }
                            }
                        }
                        ColumnLayout {
                            spacing: 2
                            HusText {
                                Layout.alignment: Qt.AlignRight
                                text: tab.fmt(tab.labels.sdu_spent, { spent: modelData.spent, cost: modelData.cost })
                                font.pixelSize: 12
                                color: HusTheme.Primary.colorTextSecondary
                            }
                            HusText {
                                Layout.alignment: Qt.AlignRight
                                visible: modelData.next_cost > 0
                                text: tab.fmt(tab.labels.sdu_next, { cost: modelData.next_cost })
                                font.pixelSize: 12
                                color: HusTheme.Primary.colorTextTertiary
                            }
                        }
                        CountStepper {
                            min: 0
                            max: modelData.max
                            value: modelData.level
                            enabled: vmGameProgress.editable
                            onStepped: function(delta) { vmGameProgress.setSduLevel(modelData.key, modelData.level + delta); }
                            onValueCommitted: function(value) { vmGameProgress.setSduLevel(modelData.key, value); }
                        }
                    }
                }
            }
        }

        // ---------------- 秘藏力量 ----------------
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8
            visible: tab.view === "vaultpower"

            Repeater {
                model: tab.view === "vaultpower" ? tab.sourceRows : []
                delegate: Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 48
                    radius: 8
                    color: HusTheme.isDark ? "#14ffffff" : "#0c000000"
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 12
                        spacing: 10
                        HusCheckBox {
                            checked: !!modelData.activated
                            enabled: vmGameProgress.editable
                            onToggled: vmGameProgress.setVaultPower(modelData.alias, checked)
                        }
                        HusText {
                            Layout.fillWidth: true
                            text: modelData.title || modelData.alias
                            color: modelData.activated ? HusTheme.Primary.colorTextBase : HusTheme.Primary.colorTextSecondary
                        }
                    }
                }
            }
            Item { Layout.fillHeight: true }
        }

        // ---------------- 台账（账号共享解锁 / 外观） ----------------
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8
            visible: tab.view === "ledger"

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                HusInput {
                    Layout.preferredWidth: 220
                    placeholderText: tab.labels.search || ""
                    text: tab.search
                    onTextChanged: tab.search = text
                }
                Repeater {
                    model: [tab.labels.filter_all || "All", tab.labels.filter_unlocked || "Unlocked",
                            tab.labels.filter_locked || "Locked"]
                    delegate: HusButton {
                        text: modelData
                        type: tab.filterMode === index ? HusButton.Type_Primary : HusButton.Type_Default
                        onClicked: tab.filterMode = index
                    }
                }
                Item { Layout.fillWidth: true }
                HusButton {
                    text: tab.buttons.unlock_all || ""
                    enabled: vmGameProgress.editable
                    onClicked: vmGameProgress.setLedgerAll(true)
                }
                HusButton {
                    text: tab.buttons.lock_all || ""
                    enabled: vmGameProgress.editable
                    onClicked: vmGameProgress.setLedgerAll(false)
                }
            }
            HusText {
                Layout.fillWidth: true
                visible: tab.cosmeticLedger
                text: tab.labels.derived_names || ""
                font.pixelSize: 12
                color: HusTheme.Primary.colorTextTertiary
                wrapMode: Text.Wrap
            }

            LockedListView {
                objectName: "ledgerList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 3
                ScrollBar.vertical: HusScrollBar { }
                model: tab.ledgerRows

                delegate: Item {
                    width: ListView.view.width - 10
                    height: modelData.header ? 30 : 38

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
                        id: ledgerRow
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
                                checked: !!modelData.unlocked
                                enabled: vmGameProgress.editable
                                onToggled: vmGameProgress.setLedgerEntry(modelData.entry, checked)
                            }
                            HusText {
                                Layout.fillWidth: true
                                text: modelData.title || ""
                                elide: Text.ElideRight
                                color: modelData.unlocked ? HusTheme.Primary.colorTextBase : "#e6a439"
                            }
                            HusText {
                                Layout.maximumWidth: 360
                                text: modelData.hint || ""
                                elide: Text.ElideRight
                                font.pixelSize: 12
                                color: HusTheme.Primary.colorTextTertiary
                            }
                        }
                        MouseArea {
                            // entry key on hover (useful when the derived name is ambiguous)
                            anchors.fill: parent
                            acceptedButtons: Qt.NoButton
                            hoverEnabled: true
                            onContainsMouseChanged: containsMouse
                                ? HoverTip.showFor(ledgerRow, modelData.entry || "", mouseX, mouseY)
                                : HoverTip.hideFor(ledgerRow)
                        }
                        Component.onDestruction: HoverTip.hideFor(ledgerRow)
                    }
                }
            }
        }
    }
}
