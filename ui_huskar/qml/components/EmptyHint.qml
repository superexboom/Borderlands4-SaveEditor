// 空态提示：只保留一行说明文字。HusEmpty 自带的收件箱插画与玻璃面板风格不符，
// 全项目统一用本组件（与 SerialInspectorPage 的空态写法一致）。
import QtQuick
import HuskarUI.Basic

HusText {
    property string description: ""

    text: description
    color: HusTheme.Primary.colorTextTertiary
    horizontalAlignment: Text.AlignHCenter
    verticalAlignment: Text.AlignVCenter
    wrapMode: Text.Wrap
}
