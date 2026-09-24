// 行/单元格复制快捷键的共享匹配逻辑：各列表获得焦点后按 Ctrl+C 复制焦点内容。
// 用法：
//   import "../components/CopyKeys.js" as CopyKeys
//   Keys.onPressed: function(event) {
//       if (CopyKeys.matchCopy(event)) { vm.copyCell(...); }
//   }
// 注意：.pragma library 里没有 StandardKey（QtQuick.Controls 枚举），
// 必须用 Qt 枚举手动比对，否则 ReferenceError: StandardKey is not defined。
.pragma library

function matchCopy(event) {
    if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_C) {
        event.accepted = true;
        return true;
    }
    return false;
}
