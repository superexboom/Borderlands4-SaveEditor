// 行内目录面板（对齐主线 InlineCatalogPicker）：单列目录，每行内嵌 [-] N [+] 步进器。
// 行 = 3px 着色左边条 + 图标 + 标题/详情；悬停仅在行文本之外另有说明（技能描述/
// 候选 hint）时经全局单例气泡 HoverTip 显示富文本详情。
// multiSelect=true 时支持 ExtendedSelection：在被多选的行上改数会批量应用到所有选中行
// （对齐主线 _edit_count/_increase_key 语义）。
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic

ColumnLayout {
    id: panel

    property string title: ""
    property var options: []           // {key,label,detail,category,accent,iconUrl,tooltip,maxCount,count,searchText}
    property var categories: []
    property string clearText: "Clear"
    property string searchPlaceholder: "🔍"
    property bool editableCount: true  // false=计数只读标签（对齐主线技能不可手输）
    property bool multiSelect: false
    property int listHeight: 300

    // keys 批量语义：被编辑行在多选集（≥2）时 keys 为整个选区
    signal countChanged(var keys, int value)
    signal countStepped(var keys, int delta)
    signal clearRequested()

    property string searchText: ""
    property string category: "all"
    property var checkedKeys: []
    property string anchorKey: ""

    SelectionStyle { id: selStyle }

    function filteredOptions() {
        var result = [];
        var q = searchText.toLowerCase();
        for (var i = 0; i < options.length; i++) {
            var opt = options[i];
            if (category !== "all" && opt.category !== category) continue;
            if (q !== "" && (opt.searchText || opt.label).toLowerCase().indexOf(q) < 0) continue;
            result.push(opt);
        }
        return result;
    }

    function selectedTotal() {
        var total = 0;
        for (var i = 0; i < options.length; i++) total += (options[i].count || 0);
        return total;
    }

    function isChecked(key) { return checkedKeys.indexOf(String(key)) >= 0; }

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
        for (var j = from; j <= to; j++) keys.push(String(opts[j].key));
        return keys;
    }

    function clickOption(key, modifiers) {
        if (!multiSelect) return;
        key = String(key);
        if (modifiers & Qt.ControlModifier) {
            var next = checkedKeys.slice();
            var at = next.indexOf(key);
            if (at >= 0) next.splice(at, 1); else next.push(key);
            checkedKeys = next;
        } else if (modifiers & Qt.ShiftModifier) {
            var range = _rangeKeys(key);
            if (range === null) { checkedKeys = [key]; anchorKey = key; }
            else checkedKeys = range;
        } else {
            checkedKeys = [key];
            anchorKey = key;
        }
    }

    // 主线批量语义：目标行在多选集里则应用到整个选区
    function editCount(key, value) {
        key = String(key);
        var targets = [key];
        if (multiSelect && checkedKeys.length >= 2 && checkedKeys.indexOf(key) >= 0)
            targets = checkedKeys.slice();
        panel.countChanged(targets, Math.max(0, value));
    }

    // +/- 按钮：相对步进（每个目标行各自 ±delta）
    function editStep(key, delta) {
        key = String(key);
        var targets = [key];
        if (multiSelect && checkedKeys.length >= 2 && checkedKeys.indexOf(key) >= 0)
            targets = checkedKeys.slice();
        panel.countStepped(targets, delta);
    }

    function accentColor(accent) {
        if (accent === "red") return "#d75b67";
        if (accent === "green") return "#52b879";
        if (accent === "blue") return "#4c8ed9";
        return "#607d8b";
    }

    function stateColor(state) {
        if (state === "legal") return "#52b879";
        if (state === "warning") return "#e6a439";
        return "#687080";
    }

    // 悬停仅在有"行文本之外"的信息时弹：tooltip 富文本描述（技能说明）或 hint。
    // 副标题（detail=技能树名）与内部字段（detail="internal · ID x"）行内已可见，不弹。
    function _rowTip(opt) {
        if (!opt) return "";
        var parts = [opt.disabledReason, opt.hint, opt.tooltip];
        return parts.filter(function(x, i, all) { return x && all.indexOf(x) === i; })
                    .map(function(x) { return HoverTip.toHtml(x); }).join("<br><br>");
    }

    onOptionsChanged: {
        var valid = {};
        for (var i = 0; i < options.length; i++) valid[String(options[i].key)] = true;
        checkedKeys = checkedKeys.filter(function(k) { return valid[k] === true; });
        if (valid[anchorKey] !== true) anchorKey = "";
    }

    spacing: 8

    // ---- 标题行 ----
    RowLayout {
        Layout.fillWidth: true
        visible: panel.title !== ""
        HusText {
            Layout.fillWidth: true
            text: panel.title
            font.bold: true
            color: HusTheme.Primary.colorTextBase
            elide: Text.ElideRight
        }
        HusText {
            text: panel.selectedTotal()
            color: HusTheme.Primary.colorPrimary
            font.bold: true
        }
        HusButton {
            visible: panel.selectedTotal() > 0
            text: panel.clearText
            onClicked: panel.clearRequested()
        }
    }

    // ---- 搜索 ----
    HusInput {
        Layout.fillWidth: true
        placeholderText: panel.searchPlaceholder
        onTextChanged: panel.searchText = text
    }

    // ---- 分类 chips ----
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

    // ---- 目录列表 ----
    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: panel.listHeight
        color: selStyle.cardBg
        border.color: selStyle.cardBorder
        border.width: 1
        radius: 10
        clip: true

        LockedListView {
            id: catalogList
            objectName: "catalogList"
            anchors.fill: parent
            anchors.margins: 4
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: HusScrollBar { }
            model: panel.filteredOptions()
            property real savedContentY: 0
            onContentYChanged: {
                HoverTip.hide();
                // VM dataChanged replaces the JS model. Restore the user's
                // previous anchor instead of jumping back to row zero.
                if (contentY > 1) savedContentY = contentY;
            }
            onMovementEnded: savedContentY = contentY
            onModelChanged: Qt.callLater(function() {
                if (savedContentY <= 1) return;
                var maxY = Math.max(0, catalogList.contentHeight - catalogList.height);
                catalogList.contentY = Math.min(savedContentY, maxY);
            })


            delegate: Item {
                id: rowDelegate
                width: ListView.view.width
                height: 58
                property bool checked: panel.isChecked(modelData.key)
                property int rowCount: modelData.count || 0
                property int rowMax: modelData.maxCount !== undefined ? Math.max(1, modelData.maxCount) : 99

                Rectangle {
                    anchors.fill: parent
                    radius: 6
                    color: rowDelegate.checked ? selStyle.bgSubtle
                         : modelData.kind === "legal" ? selStyle.legitBg
                         : modelData.kind === "warning" ? selStyle.warningBg
                         : modelData.kind === "modified" ? selStyle.invalidBg
                         : modelData.kind === "unknown" ? selStyle.unknownBg
                         : rowHover.containsMouse ? selStyle.hover
                         : "transparent"
                }
                // 主线 inlineCatalogRow：3px 着色左边条
                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 3
                    radius: 2
                    color: panel.accentColor(modelData.accent)
                }
                MouseArea {
                    id: rowHover
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: function(mouse) { panel.clickOption(modelData.key, mouse.modifiers); }
                    onEntered: HoverTip.showFor(rowDelegate, panel._rowTip(modelData), mouseX, mouseY)
                    onPositionChanged: HoverTip.showFor(rowDelegate, panel._rowTip(modelData), mouseX, mouseY)
                    onExited: HoverTip.hideFor(rowDelegate)
                }

                // MouseArea owns the delegate hover region on some Qt 6 builds;
                // keep a handler on the row itself so the rich tooltip is reliable.

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 8
                    spacing: 10
                    Rectangle {
                        visible: (modelData.iconUrl || "") !== ""
                        Layout.preferredWidth: 42
                        Layout.preferredHeight: 42
                        Layout.alignment: Qt.AlignVCenter
                        radius: 6
                        color: HusTheme.isDark ? "#1AFFFFFF" : "#0D000000"
                        Image {
                            anchors.centerIn: parent
                            source: modelData.iconUrl || ""
                            sourceSize.width: 38
                            sourceSize.height: 38
                        }
                    }
                    Column {
                        spacing: 2
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignVCenter
                        HusText {
                            width: parent.width
                            text: (modelData.marker ? modelData.marker + "  " : "") + modelData.label
                            font.bold: modelData.kind === "legal" || rowDelegate.rowCount > 0
                            font.pixelSize: 14
                            color: rowDelegate.checked ? selStyle.text : HusTheme.Primary.colorTextBase
                            elide: Text.ElideRight
                        }
                        HusText {
                            visible: (modelData.detail || "") !== ""
                            width: parent.width
                            text: modelData.detail || ""
                            font.pixelSize: 11
                            color: rowDelegate.checked ? selStyle.secondaryText
                                 : HusTheme.Primary.colorTextSecondary
                            elide: Text.ElideRight
                        }
                    }
                    // [-] N [+] 步进器（对齐主线 rowStepBtn/rowCount）
                    CountStepper {
                        min: 0
                        max: rowDelegate.rowMax
                        value: rowDelegate.rowCount
                        editable: panel.editableCount
                        Layout.alignment: Qt.AlignVCenter
                        onStepped: function(delta) { panel.editStep(modelData.key, delta); }
                        onValueCommitted: function(v) { panel.editCount(modelData.key, v); }
                    }
                }
            }
        }
    }
}
