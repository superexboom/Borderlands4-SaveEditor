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
    // 加成分两种：装备（职业模组）给的，和 SE 的额外加点
    readonly property int gear: { revision; return empty || choice || !vm ? 0 : vm.value(cell.graph, cell.i, "gear"); }
    readonly property int extra: { revision; return empty || choice || !vm ? 0 : vm.value(cell.graph, cell.i, "extra"); }
    readonly property bool active: { revision; return choice && vm ? vm.value(cell.graph, cell.i, "active") === 1 : false; }
    readonly property bool lit: choice ? active : spent > 0
    // 0 解锁，1 未解锁（层级 / 前置点数不够），2 未解锁却已加点或启用（游戏会拒绝）
    readonly property int lockState: { revision; return empty || !vm ? 0 : vm.unlockState(cell.graph, cell.i); }
    readonly property bool isSelected: vm && vm.selected && vm.selected.graph === cell.graph && vm.selected.i === cell.i
    readonly property color accent: cell.color || "#9e9e9e"

    readonly property bool hasIcon: (cell.icon || "") !== ""
    // 动作技能是宽幅插画
    implicitWidth: kind === "action" ? Math.round(size * 1.75) : size
    implicitHeight: size

    // 有图标：游戏图标本身带节点框，只在外面画选中 / 启用的光圈
    Rectangle {
        visible: !cellItem.empty && cellItem.hasIcon
                 && (cellItem.isSelected || cellItem.lockState === 2 || (cellItem.choice && cellItem.active))
        anchors.fill: parent
        anchors.margins: 1
        radius: 10
        color: "transparent"
        border.width: cellItem.isSelected || cellItem.lockState === 2 ? 3 : 2
        border.color: cellItem.lockState === 2 ? "#e05a4f" : cellItem.isSelected ? "#ffd166" : cellItem.accent
    }
    Image {
        id: icon
        visible: !cellItem.empty && cellItem.hasIcon
        anchors.fill: parent
        anchors.margins: cellItem.kind === "passive" || cellItem.kind === "perk" ? 6 : 4
        source: cellItem.cell.icon || ""
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        opacity: cellItem.lit ? 1.0 : cellItem.lockState ? 0.18 : 0.45
        Behavior on opacity { NumberAnimation { duration: 120 } }
    }

    // 没有图标：自绘格子（菱形 = 增强 / 终极，圆 = 动作技能 / 专精技能）
    Rectangle {
        id: face
        visible: !cellItem.empty && !cellItem.hasIcon
        anchors.centerIn: parent
        width: cellItem.size - 8
        height: width
        rotation: cellItem.kind === "augment" || cellItem.kind === "capstone" ? 45 : 0
        scale: rotation ? 0.78 : 1.0
        radius: cellItem.kind === "action" || cellItem.kind === "perk" ? width / 2 : 8
        color: cellItem.lit ? Qt.rgba(cellItem.accent.r, cellItem.accent.g, cellItem.accent.b, 0.28)
                            : (HusTheme.isDark ? "#22262d" : "#e9ebef")
        border.width: cellItem.isSelected ? 3 : (cellItem.lit ? 2 : 1)
        border.color: cellItem.isSelected ? "#ffd166"
                      : cellItem.lit ? cellItem.accent : (HusTheme.isDark ? "#4a505a" : "#b8bec8")
        Behavior on color { ColorAnimation { duration: 120 } }
        HusText {
            anchors.centerIn: parent
            rotation: -face.rotation
            text: cellItem.cell.initials || ""
            font.bold: true
            font.pixelSize: 17
            color: cellItem.lit ? (HusTheme.isDark ? "#ffffff" : "#1f2329") : HusTheme.Primary.colorTextTertiary
        }
    }

    // 未解锁
    Rectangle {
        visible: cellItem.lockState !== 0
        anchors.left: parent.left
        anchors.top: parent.top
        width: 18
        height: 18
        radius: 9
        color: cellItem.lockState === 2 ? "#e05a4f" : (HusTheme.isDark ? "#cc2b2f36" : "#ccffffff")
        border.color: cellItem.lockState === 2 ? "#e05a4f" : "#8a919c"
        HusIconText {
            anchors.centerIn: parent
            iconSource: HusIcon.LockOutlined
            iconSize: 11
            colorIcon: cellItem.lockState === 2 ? "#ffffff" : "#8a919c"
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
    // 加成角标：青 = 职业模组等装备，橙 = SE 额外加点
    Row {
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: 2
        Rectangle {
            visible: cellItem.gear > 0
            width: gearText.implicitWidth + 8
            height: 16
            radius: 8
            color: "#2a9d8f"
            HusText {
                id: gearText
                anchors.centerIn: parent
                text: "+" + cellItem.gear
                font.pixelSize: 11
                font.bold: true
                color: "#ffffff"
            }
        }
        Rectangle {
            visible: cellItem.extra > 0
            width: extraText.implicitWidth + 8
            height: 16
            radius: 8
            color: "#e67e22"
            HusText {
                id: extraText
                anchors.centerIn: parent
                text: "+" + cellItem.extra
                font.pixelSize: 11
                font.bold: true
                color: "#ffffff"
            }
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
