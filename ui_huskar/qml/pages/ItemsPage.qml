import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "../components"
import "../components/CopyKeys.js" as CopyKeys

// 物品总览页：对齐主线 QtItemsTab（添加条 + 搜索 + 六维筛选 + 分组树 + 右键菜单 + 悬停卡片）
ColumnLayout {
    id: page
    anchors.fill: parent
    anchors.margins: 0
    spacing: 10

    readonly property var loc: vmItems.strings
    readonly property var addLoc: loc.add_item || ({})
    readonly property var filtersLoc: loc.filters || ({})
    readonly property var actionsLoc: loc.actions || ({})

    // 焦点列（Ctrl+C 复制的目标列，点选某列即聚焦，对齐主线点选单元格复制）
    property string focusedColumn: "name"
    readonly property var columnModel: [
        { key: "name", width: 230 },
        { key: "type", width: 100 },
        { key: "manufacturer", width: 105 },
        { key: "rarity", width: 75 },
        { key: "level", width: 55 },
        { key: "flags", width: 85 },
        { key: "serial", width: 200 }
    ]
    readonly property int rowContentMargin: 8 + 2 * 18

    function columnKeyAt(x) {
        var rest = x - rowContentMargin;
        for (var i = 0; i < columnModel.length; i++) {
            if (rest < columnModel[i].width)
                return columnModel[i].key;
            rest -= columnModel[i].width;
        }
        return columnModel[columnModel.length - 1].key;
    }

    function columnBounds(key) {
        var start = rowContentMargin;
        for (var i = 0; i < columnModel.length; i++) {
            if (columnModel[i].key === key)
                return { x: start, width: columnModel[i].width };
            start += columnModel[i].width;
        }
        return { x: rowContentMargin, width: columnModel[0].width };
    }

    SelectionStyle { id: selStyle }

    Component.onCompleted: vmItems.forceRefresh()

    // ---- 添加物品条 ----
    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        HusText { text: addLoc.label_serial || ""; color: HusTheme.Primary.colorTextBase }
        HusInput {
            Layout.fillWidth: true
            text: vmItems.addSerial
            placeholderText: addLoc.placeholder_serial || ""
            onTextChanged: vmItems.setAddSerial(text)
            onAccepted: vmItems.addItem()
        }
        HusText { text: addLoc.label_flag || ""; color: HusTheme.Primary.colorTextBase }
        AppSelect {
            Layout.preferredWidth: 150
            model: vmItems.flagOptions
            currentIndex: vmItems.flagIndex
            onActivated: function(index) { vmItems.setFlagIndex(index); }
        }
        HusIconButton {
            text: addLoc.button_add || ""
            type: HusButton.Type_Primary
            iconSource: HusIcon.PlusOutlined
            enabled: vmItems.saveLoaded
            onClicked: vmItems.addItem()
        }
    }

    // ---- 搜索 ----
    HusInput {
        Layout.fillWidth: true
        placeholderText: loc.search_placeholder || ""
        onTextChanged: vmItems.setSearchText(text)
    }

    // ---- 筛选行 ----
    GridLayout {
        Layout.fillWidth: true
        columns: 8
        columnSpacing: 6
        rowSpacing: 4
        HusText { text: filtersLoc.container || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
        HusText { text: filtersLoc.type || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
        HusText { text: filtersLoc.manufacturer || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
        HusText { text: filtersLoc.rarity || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
        HusText { text: filtersLoc.flags || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
        HusText { text: filtersLoc.level || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
        HusText { text: ""; }
        HusText {
            text: vmItems.filterCountText
            color: HusTheme.Primary.colorTextSecondary
            font.pixelSize: 11
            horizontalAlignment: Text.AlignRight
        }
        AppSelect {
            Layout.fillWidth: true
            model: vmItems.filterOptions.container || []
            currentIndex: 0
            onActivated: function(index) { vmItems.setFilter("container", model[index].value); }
        }
        AppSelect {
            Layout.fillWidth: true
            model: vmItems.filterOptions.type || []
            currentIndex: 0
            onActivated: function(index) { vmItems.setFilter("type", model[index].value); }
        }
        AppSelect {
            Layout.fillWidth: true
            model: vmItems.filterOptions.manufacturer || []
            currentIndex: 0
            onActivated: function(index) { vmItems.setFilter("manufacturer", model[index].value); }
        }
        AppSelect {
            Layout.fillWidth: true
            model: vmItems.filterOptions.rarity || []
            currentIndex: 0
            onActivated: function(index) { vmItems.setFilter("rarity", model[index].value); }
        }
        AppSelect {
            Layout.fillWidth: true
            model: vmItems.filterOptions.flags || []
            currentIndex: 0
            onActivated: function(index) { vmItems.setFilter("flags", model[index].value); }
        }
        RowLayout {
            spacing: 4
            HusInputInteger {
                Layout.fillWidth: true
                min: 0
                max: 999
                value: vmItems.levelMin
                onValueModified: vmItems.setLevelMin(value)
            }
            HusInputInteger {
                Layout.fillWidth: true
                min: 0
                max: 999
                value: vmItems.levelMax
                onValueModified: vmItems.setLevelMax(value)
            }
        }
        HusButton {
            text: filtersLoc.clear || ""
            onClicked: vmItems.clearFilters()
        }
        HusText { text: ""; }
    }

    // ---- 物品树 ----
    GlassPanel {
        Layout.fillWidth: true
        Layout.fillHeight: true

        LockedListView {
            id: treeList
            anchors.fill: parent
            anchors.margins: 4
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: HusScrollBar { }
            model: vmItems.rows
            cacheBuffer: 2000
            activeFocusOnTab: true

            // Ctrl+C 复制选中行的焦点列（选中行 + 焦点列语义，对齐主线）
            Keys.onPressed: function(event) {
                if (CopyKeys.matchCopy(event))
                    vmItems.copyCell(treeList.currentIndex, page.focusedColumn);
            }

            // 滚动时行在光标下移动，立即作废悬停卡（对齐主线 Wheel 隐藏）
            onContentYChanged: vmItems.hoverCanceled()

            Connections {
                target: vmItems
                function onSelectedRowChanged(row) {
                    treeList.currentIndex = row;
                    treeList.positionViewAtIndex(row, ListView.Center);
                }
            }

            delegate: Item {
                width: treeList.width
                height: modelData.rowType === "item" ? 30 : 26

                // 组行（容器 / 类型）
                Rectangle {
                    visible: modelData.rowType !== "item"
                    anchors.fill: parent
                    color: modelData.rowType === "container"
                           ? (HusTheme.isDark ? "#26FFFFFF" : "#1A000000")
                           : (HusTheme.isDark ? "#14FFFFFF" : "#0D000000")
                    radius: 3
                    HusText {
                        anchors.fill: parent
                        anchors.leftMargin: 8 + modelData.depth * 18
                        verticalAlignment: Text.AlignVCenter
                        text: (modelData.expanded ? "▾ " : "▸ ") + modelData.text
                        color: HusTheme.Primary.colorTextBase
                        font.bold: modelData.rowType === "container"
                        elide: Text.ElideRight
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: vmItems.toggleGroup(modelData.key)
                    }
                }

                // 物品行
                Rectangle {
                    id: itemRow
                    visible: modelData.rowType === "item"
                    anchors.fill: parent
                    property bool selected: treeList.currentIndex === index
                    color: selected
                           ? selStyle.bg
                           : (index % 2 === 0 ? "transparent" : (HusTheme.isDark ? "#0AFFFFFF" : "#05000000"))
                    // 焦点列指示：选中行上焦点列的下边框（提示 Ctrl+C 复制目标）
                    Rectangle {
                        visible: itemRow.selected
                        x: page.columnBounds(page.focusedColumn).x
                        width: page.columnBounds(page.focusedColumn).width - 4
                        anchors.bottom: parent.bottom
                        height: 2
                        color: selStyle.text
                        opacity: 0.85
                    }
                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: page.rowContentMargin
                        spacing: 0
                        HusText { width: nameCol.width; text: modelData.name || ""; color: itemRow.selected ? selStyle.text : HusTheme.Primary.colorTextBase; elide: Text.ElideRight; height: parent.height; verticalAlignment: Text.AlignVCenter }
                        HusText { width: typeCol.width; text: modelData.type || ""; color: itemRow.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary; elide: Text.ElideRight; height: parent.height; verticalAlignment: Text.AlignVCenter }
                        HusText { width: mfgCol.width; text: modelData.manufacturer || ""; color: itemRow.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary; elide: Text.ElideRight; height: parent.height; verticalAlignment: Text.AlignVCenter }
                        HusText { width: rarityCol.width; text: modelData.rarity || ""; color: itemRow.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary; elide: Text.ElideRight; height: parent.height; verticalAlignment: Text.AlignVCenter }
                        HusText { width: levelCol.width; text: modelData.level || ""; color: itemRow.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary; elide: Text.ElideRight; height: parent.height; verticalAlignment: Text.AlignVCenter }
                        HusText { width: flagsCol.width; text: modelData.flags || ""; color: itemRow.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary; elide: Text.ElideRight; height: parent.height; verticalAlignment: Text.AlignVCenter }
                        HusText { width: serialCol.width; text: modelData.serial || ""; color: itemRow.selected ? selStyle.tertiaryText : HusTheme.Primary.colorTextTertiary; elide: Text.ElideRight; height: parent.height; verticalAlignment: Text.AlignVCenter; font.pixelSize: 11 }
                    }
                    MouseArea {
                        id: rowMouse
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        hoverEnabled: true
                        onClicked: function(mouse) {
                            treeList.currentIndex = index;
                            page.focusedColumn = page.columnKeyAt(mouse.x);
                            treeList.forceActiveFocus();
                            if (mouse.button === Qt.RightButton)
                                contextMenu.openFor(index, mouse.x, mouse.y);
                        }
                        onEntered: vmItems.hoverEntered(index)
                        onPositionChanged: function(mouse) {
                            // 卡片打开后冻结弹层位置（对齐 QToolTip 触发时定位）
                            if (!hoverCard.visible) {
                                var p = rowMouse.mapToItem(page, mouse.x, mouse.y);
                                hoverCard.lastX = p.x;
                                hoverCard.lastY = p.y;
                            }
                            // 与主线 viewport MouseMove 一致：每次移动都向 VM 重报目标行
                            vmItems.hoverEntered(index);
                        }
                        onExited: vmItems.hoverExited(index)
                    }
                }
            }
        }
    }

    // 列宽参考（隐藏 header 用于对齐）
    Row {
        visible: false
        HusText { id: nameCol; width: 230 }
        HusText { id: typeCol; width: 100 }
        HusText { id: mfgCol; width: 105 }
        HusText { id: rarityCol; width: 75 }
        HusText { id: levelCol; width: 55 }
        HusText { id: flagsCol; width: 85 }
        HusText { id: serialCol; width: 200 }
    }

    // ---- 悬停卡片（VM 侧 700ms 防抖状态机；卡片经 QTextDocument 离屏渲染为 PNG，
    //      QML Text 富文本画不了单元格 background-image，会黑底/错位） ----
    Connections {
        target: vmItems
        function onHoverCardRequested(row, info) {
            hoverCardImage.source = info.url;
            hoverCard.cardWidth = info.width;
            hoverCard.cardHeight = info.height;
            hoverCard.open();
        }
        function onHoverCardDismissed() {
            hoverCard.close();
            hoverCardImage.source = "";
        }
    }

    Popup {
        id: hoverCard
        padding: 0
        closePolicy: Popup.NoAutoClose
        property int lastX: 0
        property int lastY: 0
        property real cardWidth: 0
        property real cardHeight: 0
        background: Rectangle {
            color: "transparent"
            border.color: HusTheme.isDark ? "#66505060" : "#59B4B4C8"
            radius: 4
        }
        contentItem: Item {
            implicitWidth: hoverCard.cardWidth
            implicitHeight: hoverCard.cardHeight
            Image {
                id: hoverCardImage
                width: hoverCard.cardWidth
                height: hoverCard.cardHeight
                cache: false
                smooth: true
            }
        }
        x: Math.min(Math.max(0, page.width - cardWidth - 14), Math.max(0, lastX + 30))
        y: Math.min(Math.max(0, page.height - cardHeight - 14), Math.max(0, lastY + 24))
    }

    // ---- 右键菜单 ----
    HusModal {
        id: contextMenu
        width: 220
        closable: true
        property int row: -1
        function openFor(row, _x, _y) {
            contextMenu.row = row;
            vmItems.hoverCanceled();
            title = "";
            open();
        }
        contentDelegate: Item {
            implicitHeight: menuColumn.implicitHeight
            ColumnLayout {
                id: menuColumn
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: 2
                Repeater {
                    model: [
                        { label: page.actionsLoc.copy_name || "Copy name", field: "name" },
                        { label: page.actionsLoc.copy_serial || "Copy serial", field: "serial" },
                        { label: page.actionsLoc.copy_decoded || "Copy decoded", field: "decoded" },
                        { label: page.actionsLoc.copy_parts || "Copy parts", field: "parts" }
                    ]
                    delegate: HusButton {
                        Layout.fillWidth: true
                        text: modelData.label
                        onClicked: {
                            vmItems.copyItemField(contextMenu.row, modelData.field);
                            contextMenu.close();
                        }
                    }
                }
            }
        }
    }
}
