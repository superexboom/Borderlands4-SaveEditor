import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic

// 技能树的一个格子（技能树页）：被动技能 = 加点格，增强 / 终极 / 动作技能 / 专精技能 = 开关格。
// 数值从 vm.value() 读取并依赖 revision；左键 加点 / 切换，右键 减点，点击同时选中显示详情。
Item {
    id: cellItem

    property var cell: ({})
    property var vm: null
    property int revision: 0
    property int size: 72

    readonly property string kind: cell.kind || "empty"
    readonly property bool empty: kind === "empty"
    readonly property bool choice: kind === "augment" || kind === "capstone" || kind === "action" || kind === "perk"
    readonly property int spent: { revision; return empty || choice || !vm ? 0 : vm.value(cell.graph, cell.i, "spent"); }
    readonly property int bonus: { revision; return empty || choice || !vm ? 0 : vm.value(cell.graph, cell.i, "bonus"); }
    readonly property bool active: { revision; return choice && vm ? vm.value(cell.graph, cell.i, "active") === 1 : false; }
    readonly property bool lit: choice ? active : spent > 0
    readonly property bool isSelected: vm && vm.selected && vm.selected.graph === cell.graph && vm.selected.i === cell.i
    readonly property color accent: cell.color || "#9e9e9e"

    implicitWidth: size
    implicitHeight: size

    Rectangle {
        id: face
        visible: !cellItem.empty
        anchors.centerIn: parent
        width: cellItem.size - 8
        height: width
        // 增强 / 终极画成菱形，和游戏里一样
        rotation: cellItem.kind === "augment" || cellItem.kind === "capstone" ? 45 : 0
        scale: rotation ? 0.78 : 1.0
        radius: cellItem.kind === "action" || cellItem.kind === "perk" ? width / 2 : 8
        color: cellItem.lit ? Qt.rgba(cellItem.accent.r, cellItem.accent.g, cellItem.accent.b, 0.28)
                            : (HusTheme.isDark ? "#22262d" : "#e9ebef")
        border.width: cellItem.isSelected ? 3 : (cellItem.lit ? 2 : 1)
        border.color: cellItem.isSelected ? "#ffd166"
                      : cellItem.lit ? cellItem.accent : (HusTheme.isDark ? "#4a505a" : "#b8bec8")
        Behavior on color { ColorAnimation { duration: 120 } }

        Image {
            id: icon
            anchors.fill: parent
            anchors.margins: 6
            rotation: -face.rotation
            source: cellItem.cell.icon || ""
            visible: source != ""
            fillMode: Image.PreserveAspectFit
            sourceSize.width: 96
            sourceSize.height: 96
            opacity: cellItem.lit ? 1.0 : 0.55
        }
        HusText {
            anchors.centerIn: parent
            rotation: -face.rotation
            visible: !icon.visible
            text: cellItem.cell.initials || ""
            font.bold: true
            font.pixelSize: 17
            color: cellItem.lit ? (HusTheme.isDark ? "#ffffff" : "#1f2329") : HusTheme.Primary.colorTextTertiary
        }
    }

    // 已加 / 上限
    Rectangle {
        visible: !cellItem.empty && !cellItem.choice
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        width: pointsText.implicitWidth + 10
        height: 16
        radius: 8
        color: HusTheme.isDark ? "#e0181b20" : "#e0ffffff"
        border.color: cellItem.spent >= cellItem.cell.max && cellItem.cell.max > 0 ? cellItem.accent : "transparent"
        HusText {
            id: pointsText
            anchors.centerIn: parent
            text: cellItem.spent + "/" + (cellItem.cell.max || 0)
            font.pixelSize: 11
            font.bold: cellItem.spent > 0
            color: cellItem.spent > 0 ? HusTheme.Primary.colorTextBase : HusTheme.Primary.colorTextTertiary
        }
    }
    // 超限
    Rectangle {
        visible: cellItem.bonus > 0
        anchors.right: parent.right
        anchors.top: parent.top
        width: bonusText.implicitWidth + 8
        height: 16
        radius: 8
        color: "#e67e22"
        HusText {
            id: bonusText
            anchors.centerIn: parent
            text: "+" + cellItem.bonus
            font.pixelSize: 11
            font.bold: true
            color: "#ffffff"
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: !cellItem.empty && cellItem.vm !== null
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onClicked: function(mouse) {
            cellItem.vm.select(cellItem.cell.graph, cellItem.cell.i);
            if (cellItem.choice) {
                if (mouse.button === Qt.LeftButton) cellItem.vm.toggle(cellItem.cell.graph, cellItem.cell.i);
            } else {
                cellItem.vm.step(cellItem.cell.graph, cellItem.cell.i, "spent", mouse.button === Qt.LeftButton ? 1 : -1);
            }
        }
        onContainsMouseChanged: {
            if (containsMouse) HoverTip.showFor(cellItem, "<b>" + (cellItem.cell.name || "") + "</b>", width / 2, height);
            else HoverTip.hideFor(cellItem);
        }
        Component.onDestruction: HoverTip.hideFor(cellItem)
    }
}
