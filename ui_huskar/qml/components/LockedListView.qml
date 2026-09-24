// 滚动锁定的 ListView：滚轮事件完全消费，到边界不冒泡给外层页面。
// 滚轮为平滑动画滚动（每格约 3 行，对齐主线列表手感，不再一次跳半屏）；
// 内容/视口高度变化后自动回夹 contentY，避免越界滚出空白区域。
// 注意：WheelHandler 不是 Item，handler 内的 parent 解析不到本视图，必须用显式 id 引用。
import QtQuick
import QtQuick.Controls

ListView {
    id: lockedList
    clip: true
    boundsBehavior: Flickable.StopAtBounds

    // 每格滚轮的滚动行数
    property int wheelLines: 3

    NumberAnimation {
        id: wheelAnim
        target: lockedList
        property: "contentY"
        duration: 200
        easing.type: Easing.OutCubic
    }

    function _clampY() {
        var maxY = Math.max(0, lockedList.contentHeight - lockedList.height);
        wheelAnim.stop();
        if (lockedList.contentY > maxY) lockedList.contentY = maxY;
        if (lockedList.contentY < 0) lockedList.contentY = 0;
    }
    onContentHeightChanged: _clampY()
    onHeightChanged: _clampY()
    // 用户拖拽开始时停掉滚轮动画，避免争夺 contentY。
    // 注意不能用 onMovementStarted：程序化 contentY 变化（含本动画）也会触发它，
    // 会造成动画启动即自停、滚轮完全失效。
    onDragStarted: wheelAnim.stop()
    onMovementEnded: _clampY()

    WheelHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: function(event) {
            var dy = event.angleDelta.y;
            if (dy !== 0) {
                var rowH = lockedList.count > 0 ? lockedList.contentHeight / lockedList.count : 32;
                var step = (dy / 120) * Math.max(48, rowH * lockedList.wheelLines);
                var maxY = Math.max(0, lockedList.contentHeight - lockedList.height);
                var target = Math.max(0, Math.min(maxY, lockedList.contentY - step));
                if (target !== lockedList.contentY) {
                    wheelAnim.stop();
                    wheelAnim.to = target;
                    wheelAnim.restart();
                }
            }
            event.accepted = true;
        }
    }
}
