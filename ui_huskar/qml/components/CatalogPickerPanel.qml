// 目录选择面板（对齐主线 CatalogPicker 双栏样式与交互）：
// 全宽搜索 + 分类/子分类 chips；左卡=可选列表（ExtendedSelection：单击选中、
// Ctrl 切换、Shift 范围、双击添加、批量“添加所选”）；右卡=“已选 n” + 已选列表
// （多选后改某行计数批量应用到所有选中行）+ 清空。
// legit 候选提示对齐主线 set_candidate_states：合法=蓝底加粗、警告=橙底，
// 标记符拼在文本前缀（不再单独渲染彩色 ✓/! 图标）。
// 行悬停：有附加信息（禁用原因/候选 hint/富文本描述）时经全局单例 HoverTip 弹出。
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic

ColumnLayout {
    id: panel

    property string title: ""
    property var options: []
    property var categories: []
    property var subcategories: []
    property var entries: []
    property bool stackable: true
    property bool emphasizeLabels: false
    property bool emphasizeDetails: false
    // Preserve the compact height used by equipment and class-mod panels;
    // the enhancement 247 builder opts into its larger viewport explicitly.
    property int listHeight: 248
    property string clearText: "Clear"
    property string addText: "Add selected →"
    property string availText: "Available"
    property string selectedText: "Selected"

    signal addRequested(var keys)
    signal removeRequested(int index)
    signal countChanged(var indices, int value)
    signal countStepped(var indices, int delta)
    signal clearRequested()

    property string searchText: ""
    property string category: "all"
    property string subcategory: "all"
    // 可选列表选中 key 集 / 已选列表选中下标集（主线 ExtendedSelection 语义）
    property var checkedKeys: []
    property var checkedEntries: []
    // Shift 范围选择的锚点（最后一次普通单击）
    property string anchorKey: ""
    property int anchorEntry: -1

    SelectionStyle { id: selStyle }

    function filteredOptions() {
        var result = [];
        var q = searchText.toLowerCase();
        for (var i = 0; i < options.length; i++) {
            var opt = options[i];
            if (category !== "all" && opt.category !== category) continue;
            if (subcategories.length > 0 && subcategory !== "all" && opt.subcategory !== subcategory) continue;
            if (q !== "" && (opt.searchText || opt.label).toLowerCase().indexOf(q) < 0) continue;
            result.push(opt);
        }
        return result;
    }

    function isOptionChecked(key) {
        return checkedKeys.indexOf(String(key)) >= 0;
    }

    function _rangeKeys(toKey) {
        var opts = filteredOptions();
        var from = -1, to = -1;
        for (var i = 0; i < opts.length; i++) {
            var k = String(opts[i].key);
            if (k === anchorKey) from = i;
            if (k === String(toKey)) to = i;
        }
        if (from < 0 || to < 0) return null;
        if (from > to) { var t = from; from = to; to = t; }
        var keys = [];
        for (var j = from; j <= to; j++)
            if (!opts[j].disabled) keys.push(String(opts[j].key));
        return keys;
    }

    // 主线 QListWidget ExtendedSelection：单击替换选区、Ctrl 切换、Shift 锚点范围
    function clickOption(key, modifiers) {
        key = String(key);
        if (modifiers & Qt.ControlModifier) {
            var next = checkedKeys.slice();
            var at = next.indexOf(key);
            if (at >= 0) next.splice(at, 1); else next.push(key);
            checkedKeys = next;
        } else if (modifiers & Qt.ShiftModifier) {
            var range = _rangeKeys(key);
            if (range === null) {
                checkedKeys = [key];
                anchorKey = key;
            } else {
                checkedKeys = range;
            }
        } else {
            checkedKeys = [key];
            anchorKey = key;
        }
    }

    // 主线 _on_avail_double：双击项在选区里则加入整个选区，否则只加它自己
    function doubleClickOption(key) {
        key = String(key);
        var keys = checkedKeys.indexOf(key) >= 0 ? checkedKeys.slice() : [key];
        if (keys.length > 0) {
            panel.addRequested(keys);
            checkedKeys = [];
        }
    }

    function addChecked() {
        if (checkedKeys.length === 0) return;
        panel.addRequested(checkedKeys.slice());
        checkedKeys = [];
    }

    function isEntryChecked(index) {
        return checkedEntries.indexOf(index) >= 0;
    }

    function clickEntry(index, modifiers) {
        if (modifiers & Qt.ControlModifier) {
            var next = checkedEntries.slice();
            var at = next.indexOf(index);
            if (at >= 0) next.splice(at, 1); else next.push(index);
            next.sort(function(a, b) { return a - b; });
            checkedEntries = next;
        } else if (modifiers & Qt.ShiftModifier && anchorEntry >= 0) {
            var from = Math.min(anchorEntry, index), to = Math.max(anchorEntry, index);
            var range = [];
            for (var i = from; i <= to; i++) range.push(i);
            checkedEntries = range;
        } else {
            checkedEntries = [index];
            anchorEntry = index;
        }
    }

    // 与主线 _edit_count 一致：被编辑行处于多选集（≥2）→ 计数批量应用到所有选中行
    function entryCountEdited(index, value) {
        if (checkedEntries.length >= 2 && checkedEntries.indexOf(index) >= 0)
            panel.countChanged(checkedEntries.slice(), value);
        else
            panel.countChanged([index], value);
    }

    // 主线 +/- 按钮语义：相对步进，每个目标行各自 ±delta（不是同步成同一个数）
    function entryCountStepped(index, delta) {
        if (checkedEntries.length >= 2 && checkedEntries.indexOf(index) >= 0)
            panel.countStepped(checkedEntries.slice(), delta);
        else
            panel.countStepped([index], delta);
    }

    function selectedTotal() {
        var total = 0;
        for (var i = 0; i < entries.length; i++) total += (entries[i].count || 1);
        return total;
    }

    function stateColor(state) {
        if (state === "legal") return "#52b879";
        if (state === "warning") return "#e6a439";
        return "#687080";
    }

    // ---- 行悬停详情（对齐主线 picker tooltip：禁用原因 + 候选提示 + 完整文本） ----
    function richDetail(value) {
        var text = String(value || "");
        if (HusTheme.isDark) return text;
        return text.replace(/#d7dee8/ig, "#374151")
                   .replace(/#ffffff/ig, "#374151")
                   .replace(/#e8e8ec/ig, "#374151");
    }

    // 仅当确有附加信息时才弹（副标题/内部 ID 等与行文本相同的字段不弹，避免噪音）
    function _rowTip(opt) {
        if (!opt) return "";
        var parts = [opt.disabledReason, opt.hint, opt.tooltip];
        return parts.filter(function(x, i, all) { return x && all.indexOf(x) === i; })
                    .map(function(x) { return HoverTip.toHtml(x); }).join("<br><br>");
    }

    function _hoverOption(list, pos) {
        if (!list) return null;
        var opts = filteredOptions();
        var row = list.indexAt(pos.x, pos.y + list.contentY);
        if (row < 0 || row >= opts.length) return null;
        return opts[row];
    }

    onOptionsChanged: {
        var valid = {};
        for (var i = 0; i < options.length; i++) valid[String(options[i].key)] = true;
        checkedKeys = checkedKeys.filter(function(k) { return valid[k] === true; });
        if (valid[anchorKey] !== true) anchorKey = "";
    }
    onEntriesChanged: {
        checkedEntries = checkedEntries.filter(function(i) { return i >= 0 && i < entries.length; });
        if (anchorEntry >= entries.length) anchorEntry = -1;
    }

    spacing: 8

    // ---- 标题行 + 候选计数 ----
    RowLayout {
        Layout.fillWidth: true
        visible: panel.title !== ""
        HusText {
            Layout.fillWidth: true
            text: panel.title
            font.bold: true
            color: HusTheme.Primary.colorTextSecondary
            elide: Text.ElideRight
        }
        HusText {
            text: panel.filteredOptions().length + " / " + panel.options.length
            color: HusTheme.Primary.colorTextSecondary
            font.pixelSize: 11
        }
    }

    HusInput {
        Layout.fillWidth: true
        placeholderText: "🔍"
        onTextChanged: panel.searchText = text
    }

    // 分类 chips
    Flow {
        Layout.fillWidth: true
        spacing: 6
        visible: panel.categories.length > 1
        Repeater {
            model: panel.categories
            delegate: Row {
                spacing: 4
                Rectangle {
                    width: 7; height: 7; radius: 2
                    anchors.verticalCenter: parent.verticalCenter
                    color: panel.stateColor(modelData.candidateState)
                }
                HusButton {
                    text: modelData.label
                    type: panel.category === modelData.key ? HusButton.Type_Primary : HusButton.Type_Default
                    onClicked: panel.category = modelData.key
                }
            }
        }
    }

    // 子分类 chips（enhancement 的 247 使用）
    Flow {
        Layout.fillWidth: true
        spacing: 6
        visible: panel.subcategories.length > 1
        Repeater {
            model: panel.subcategories
            delegate: Row {
                spacing: 4
                Rectangle {
                    width: 7; height: 7; radius: 2
                    anchors.verticalCenter: parent.verticalCenter
                    color: panel.stateColor(modelData.candidateState)
                }
                HusButton {
                    text: modelData.label
                    type: panel.subcategory === modelData.key ? HusButton.Type_Primary : HusButton.Type_Default
                    onClicked: panel.subcategory = modelData.key
                }
            }
        }
    }

    // ---- 主体：左卡=可选 | 右卡=已选（主线 catalogCard 样式） ----
    RowLayout {
        Layout.fillWidth: true
        Layout.preferredHeight: panel.listHeight
        spacing: 10

        // 左卡：可选列表 + 批量添加
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: selStyle.cardBg
            border.color: selStyle.cardBorder
            border.width: 1
            radius: 10
            clip: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 6

                HusText {
                    text: panel.availText
                    color: HusTheme.Primary.colorTextSecondary
                    font.pixelSize: 12
                    font.bold: true
                }

                LockedListView {
                    id: optionsList
                    objectName: "optionsList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: HusScrollBar { }
                    model: panel.filteredOptions()
                    property real savedContentY: 0
                    onContentYChanged: {
                        HoverTip.hide();
                        if (contentY > 1) savedContentY = contentY;
                    }
                    onMovementEnded: savedContentY = contentY
                    onModelChanged: Qt.callLater(function() {
                        if (savedContentY <= 1) return;
                        var maxY = Math.max(0, optionsList.contentHeight - optionsList.height);
                        optionsList.contentY = Math.min(savedContentY, maxY);
                    })
                    // 行悬停详情（对齐主线 picker tooltip；HoverTip 为全局单例气泡）

                    delegate: Item {
                        id: optDelegate
                        width: ListView.view.width
                        height: optRow.implicitHeight + 12
                        property bool checked: panel.isOptionChecked(modelData.key)
                        Rectangle {
                            anchors.fill: parent
                            radius: 6
                            color: optDelegate.checked ? selStyle.bg
                                 : modelData.kind === "legal" ? selStyle.legitBg
                                 : modelData.kind === "warning" ? selStyle.warningBg
                                 : modelData.kind === "modified" ? selStyle.invalidBg
                                 : modelData.kind === "unknown" ? selStyle.unknownBg
                                 : optHover.containsMouse ? selStyle.hover
                                 : "transparent"
                        }
                        RowLayout {
                            id: optRow
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.margins: 8
                            spacing: 6
                            Image {
                                visible: modelData.iconUrl !== undefined && modelData.iconUrl !== ""
                                source: modelData.iconUrl || ""
                                sourceSize.width: 24
                                sourceSize.height: 24
                            }
                            Column {
                                spacing: 1
                                Layout.fillWidth: true
                                HusText {
                                    width: parent.width
                                    // 主线：标记符拼进文本（"✓  名称"），合法项加粗
                                    text: (modelData.marker ? modelData.marker + "  " : "")
                                          + modelData.label
                                          + (modelData.disabled && modelData.disabledReason
                                             ? "  (" + modelData.disabledReason + ")" : "")
                                    font.bold: panel.emphasizeLabels || modelData.kind === "legal"
                                    font.pixelSize: panel.emphasizeLabels ? 16 : 14
                                    color: optDelegate.checked ? selStyle.text
                                         : modelData.disabled ? HusTheme.Primary.colorTextDisabled
                                         : modelData.accent === "blue" ? "#4a90e2"
                                         : modelData.accent === "red" ? "#ff6b6b"
                                         : modelData.accent === "green" ? "#78dba9"
                                         : HusTheme.Primary.colorTextBase
                                    elide: Text.ElideRight
                                }
                                HusText {
                                    visible: modelData.detail !== undefined && modelData.detail !== ""
                                    width: parent.width
                                    text: panel.richDetail(modelData.detail || "")
                                    textFormat: Text.RichText
                                    wrapMode: Text.Wrap
                                    color: optDelegate.checked ? selStyle.secondaryText
                                         : HusTheme.Primary.colorTextSecondary
                                    font.pixelSize: panel.emphasizeDetails && modelData.detail ? 15 : (modelData.detail ? 13 : 11)
                                    font.bold: panel.emphasizeDetails && modelData.detail
                                }
                            }
                        }
                        MouseArea {
                            id: optHover
                            anchors.fill: parent
                            hoverEnabled: true
                            enabled: !modelData.disabled
                            onClicked: function(mouse) { panel.clickOption(modelData.key, mouse.modifiers); }
                            onDoubleClicked: function(mouse) { panel.doubleClickOption(modelData.key); }
                            onEntered: HoverTip.showFor(optDelegate, panel._rowTip(modelData), mouseX, mouseY)
                            onPositionChanged: HoverTip.showFor(optDelegate, panel._rowTip(modelData), mouseX, mouseY)
                            onExited: HoverTip.hideFor(optDelegate)
                        }


                    }
                }

                // 批量添加（主线 catalogAddBtn：卡内全宽按钮）
                HusButton {
                    objectName: "addButton"
                    Layout.fillWidth: true
                    text: panel.addText
                    type: HusButton.Type_Primary
                    enabled: panel.checkedKeys.length > 0
                    onClicked: panel.addChecked()
                }
            }
        }

        // 右卡：已选列表 + 清空
        Rectangle {
            Layout.preferredWidth: Math.max(260, panel.width * 0.38)
            Layout.fillHeight: true
            color: selStyle.cardBg
            border.color: selStyle.cardBorder
            border.width: 1
            radius: 10
            clip: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    HusText {
                        Layout.fillWidth: true
                        text: panel.selectedText + " " + panel.selectedTotal()
                        font.bold: true
                        color: HusTheme.Primary.colorPrimary
                        elide: Text.ElideRight
                    }
                    HusButton {
                        visible: panel.entries.length > 0
                        text: panel.clearText
                        onClicked: panel.clearRequested()
                    }
                }

                LockedListView {
                    id: entriesList
                    objectName: "entriesList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: HusScrollBar { }
                    model: panel.entries
                    onContentYChanged: HoverTip.hide()
                    // 已选行不再弹悬停（主线 SelectedRow tooltip 仅长文本省略时有用，
                    // 日常全可见时弹气泡只是噪音）
                    delegate: Item {
                        id: entryDelegate
                        width: ListView.view.width
                        height: entryColumn.implicitHeight + 8
                        property bool checked: panel.isEntryChecked(index)
                        Rectangle {
                            anchors.fill: parent
                            radius: 6
                            color: entryDelegate.checked ? selStyle.bg
                                 : modelData.kind === "legal" ? selStyle.legitBg
                                 : modelData.kind === "warning" ? selStyle.warningBg
                                 : modelData.kind === "modified" ? selStyle.invalidBg
                                 : modelData.kind === "unknown" ? selStyle.unknownBg
                                 : entryHover.containsMouse ? selStyle.hover
                                 : "transparent"
                        }
                        MouseArea {
                            id: entryHover
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: function(mouse) { panel.clickEntry(index, mouse.modifiers); }
                            onEntered: HoverTip.showFor(entryDelegate, panel._rowTip(modelData), mouseX, mouseY)
                            onPositionChanged: HoverTip.showFor(entryDelegate, panel._rowTip(modelData), mouseX, mouseY)
                            onExited: HoverTip.hideFor(entryDelegate)
                        }
                        RowLayout {
                            id: entryColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 8
                            anchors.rightMargin: 4
                            spacing: 6
                            Column {
                                Layout.fillWidth: true
                                spacing: 2
                                HusText {
                                    width: parent.width
                                    text: (modelData.marker ? modelData.marker + "  " : "") + modelData.label
                                    color: entryDelegate.checked ? selStyle.text
                                         : HusTheme.Primary.colorTextBase
                                    font.pixelSize: panel.emphasizeLabels ? 16 : 14
                                    font.bold: true
                                    elide: Text.ElideRight
                                }
                                HusText {
                                    visible: modelData.detail !== undefined && modelData.detail !== ""
                                    width: parent.width
                                    text: panel.richDetail(modelData.detail || "")
                                    textFormat: Text.RichText
                                    wrapMode: Text.Wrap
                                    color: entryDelegate.checked ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary
                                    font.pixelSize: panel.emphasizeDetails && modelData.detail ? 15 : 13
                                    font.bold: panel.emphasizeDetails && modelData.detail
                                }
                            }
                            CountStepper {
                                visible: panel.stackable
                                min: 1
                                max: modelData.maxCount !== undefined ? Math.max(999999, modelData.maxCount) : 999999
                                value: modelData.count
                                Layout.alignment: Qt.AlignVCenter
                                onStepped: function(delta) { panel.entryCountStepped(index, delta); }
                                onValueCommitted: function(v) { panel.entryCountEdited(index, v); }
                            }
                            HusIconButton {
                                iconSource: HusIcon.CloseOutlined
                                contentDescription: "remove"
                                Layout.alignment: Qt.AlignVCenter
                                onClicked: panel.removeRequested(index)
                            }
                        }
                    }
                }
            }
        }
    }
}
