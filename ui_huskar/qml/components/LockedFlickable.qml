// 滚动锁定的 Flickable：滚轮事件完全消费，到边界不冒泡给外层页面。
// 用法与 Flickable 完全一致（contentWidth/contentHeight/ScrollBar 等照常）。
// 滚轮为平滑动画滚动（不再一次跳半屏）；内容/视口高度变化后自动回夹 contentY，避免越界空白。
// 注意：WheelHandler 不是 Item，handler 内的 parent 解析不到本视图，必须用显式 id 引用。
import QtQuick
import QtQuick.Controls

Flickable {
    id: lockedFlick
    clip: true
    boundsBehavior: Flickable.StopAtBounds

    // 每格滚轮滚动距离（此前一次约半屏 240px，过于突兀）
    property int wheelStep: 140

    NumberAnimation {
        id: wheelAnim
        target: lockedFlick
        property: "contentY"
        duration: 200
        easing.type: Easing.OutCubic
    }

    function _clampY() {
        var maxY = Math.max(0, lockedFlick.contentHeight - lockedFlick.height);
        wheelAnim.stop();
        if (lockedFlick.contentY > maxY) lockedFlick.contentY = maxY;
        if (lockedFlick.contentY < 0) lockedFlick.contentY = 0;
    }
    onContentHeightChanged: _clampY()
    onHeightChanged: _clampY()
    // 用户拖拽开始时停掉滚轮动画（不能用 onMovementStarted：动画自身也会触发它）
    onDragStarted: { wheelAnim.stop(); HoverTip.hide(); }
    onMovementEnded: _clampY()

    WheelHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: function(event) {
            HoverTip.hide();
            var dy = event.angleDelta.y;
            if (dy !== 0) {
                var step = (dy / 120) * lockedFlick.wheelStep;
                var maxY = Math.max(0, lockedFlick.contentHeight - lockedFlick.height);
                var target = Math.max(0, Math.min(maxY, lockedFlick.contentY - step));
                if (target !== lockedFlick.contentY) {
                    wheelAnim.stop();
                    wheelAnim.to = target;
                    wheelAnim.restart();
                }
            }
            event.accepted = true;
        }
    }
}
