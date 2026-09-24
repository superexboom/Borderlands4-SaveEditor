// 计数步进器：[-] N [+]，对齐主线 SelectedRow/InlineCatalogRow 的样式。
// 按钮为相对步进（stepped ±1），中间文本可编辑时提交绝对值（valueCommitted）。
// 按钮带按压小动画；不再使用 HusInputInteger（其上下箭头动画会让连点越过中线
// 变成反向递减，越点越少）。
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic

RowLayout {
    id: stepper

    property int value: 1
    property int min: 0
    property int max: 99
    property bool editable: true
    property int stepSize: 1

    signal stepped(int delta)
    signal valueCommitted(int value)

    function clampValue(v) {
        return Math.max(stepper.min, Math.min(stepper.max, Math.round(v)));
    }

    function commitText(text) {
        var n = parseInt(text);
        if (isNaN(n)) return;
        var v = clampValue(n);
        if (v !== stepper.value)
            stepper.valueCommitted(v);
    }

    component StepButton: HusButton {
        property int delta: 0
        Layout.preferredWidth: 28
        Layout.preferredHeight: 28
        Layout.alignment: Qt.AlignVCenter
        padding: 0
        scale: down ? 0.85 : 1.0
        Behavior on scale {
            NumberAnimation { duration: 100; easing.type: Easing.OutCubic }
        }
        onClicked: stepper.stepped(delta)
    }

    spacing: 4

    StepButton {
        text: "−"
        delta: -stepper.stepSize
        enabled: stepper.value > stepper.min
    }
    HusInput {
        visible: stepper.editable
        Layout.preferredWidth: 44
        Layout.preferredHeight: 28
        Layout.alignment: Qt.AlignVCenter
        horizontalAlignment: Text.AlignHCenter
        text: stepper.value
        validator: IntValidator { bottom: stepper.min; top: stepper.max }
        onEditingFinished: stepper.commitText(text)
        onActiveFocusChanged: if (!activeFocus) stepper.commitText(text)
    }
    HusText {
        visible: !stepper.editable
        Layout.preferredWidth: 32
        Layout.alignment: Qt.AlignVCenter
        horizontalAlignment: Text.AlignHCenter
        text: stepper.value
        font.bold: true
        color: stepper.value > stepper.min ? HusTheme.Primary.colorPrimary
             : HusTheme.Primary.colorTextDisabled
    }
    StepButton {
        text: "+"
        delta: stepper.stepSize
        enabled: stepper.value < stepper.max
    }
}
