// 游戏进度页左侧分类列表：可选按 area 分组表头，每项显示 完成数/总数 与细进度条。
import QtQuick
import QtQuick.Controls
import HuskarUI.Basic

LockedListView {
    id: list

    property var categories: []
    property string current: ""
    // 分组依据字段（如 "area"）；为空则不插入分组表头
    property string groupField: ""
    signal picked(string key)

    SelectionStyle { id: selStyle }

    spacing: 2
    ScrollBar.vertical: HusScrollBar { }
    model: {
        if (!groupField)
            return categories;
        var rows = [], last = null;
        for (var i = 0; i < categories.length; i++) {
            var row = categories[i];
            if (row[groupField] !== last) {
                rows.push({ header: true, title: row[groupField] });
                last = row[groupField];
            }
            rows.push(row);
        }
        return rows;
    }

    delegate: Item {
        id: rowItem
        width: ListView.view.width
        height: modelData.header ? 30 : 46
        readonly property bool selected: !modelData.header && modelData.key === list.current

        HusText {
            visible: !!modelData.header
            anchors.left: parent.left
            anchors.leftMargin: 6
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 4
            text: modelData.title || ""
            font.bold: true
            font.pixelSize: 12
            color: HusTheme.Primary.colorTextTertiary
        }

        Rectangle {
            visible: !modelData.header
            anchors.fill: parent
            radius: 6
            color: rowItem.selected ? selStyle.bg : (rowHover.containsMouse ? selStyle.hover : "transparent")

            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 4
                Item {
                    width: parent.width
                    height: titleText.implicitHeight
                    HusText {
                        id: titleText
                        anchors.left: parent.left
                        anchors.right: countText.left
                        anchors.rightMargin: 6
                        text: modelData.title || ""
                        elide: Text.ElideRight
                        color: rowItem.selected ? selStyle.text : HusTheme.Primary.colorTextBase
                    }
                    HusText {
                        id: countText
                        anchors.right: parent.right
                        // 无可追踪项（如只有设施的小地图）显示「—」而不是 0/0
                        text: modelData.total > 0 ? (modelData.done || 0) + "/" + modelData.total : "—"
                        font.pixelSize: 12
                        color: rowItem.selected ? selStyle.secondaryText
                             : (modelData.total > 0 && modelData.done >= modelData.total ? "#78dba9"
                                                                                         : HusTheme.Primary.colorTextSecondary)
                    }
                }
                Rectangle {
                    width: parent.width
                    height: 3
                    radius: 1.5
                    color: HusTheme.isDark ? "#22ffffff" : "#18000000"
                    Rectangle {
                        width: modelData.total > 0 ? parent.width * Math.min(1, modelData.done / modelData.total) : 0
                        height: parent.height
                        radius: parent.radius
                        color: modelData.total > 0 && modelData.done >= modelData.total ? "#78dba9" : "#4a90e2"
                    }
                }
            }
            MouseArea {
                id: rowHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: list.picked(modelData.key)
            }
        }
    }
}
