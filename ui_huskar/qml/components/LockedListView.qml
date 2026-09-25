// 滚动锁定的 ListView：滚轮事件完全消费，到边界不冒泡给外层页面。
// 滚轮为平滑动画滚动（每格约 3 行，对齐主线列表手感，不再一次跳半屏）；
// 内容/视口高度变化后自动回到合法范围，避免越界滚出空白区域。
//
// 边界必须以 originY 为基准：行高不一的列表（描述换行等）只能估算未创建行的高度，
// 滚到底再往回滚时 ListView 会重估并移动 originY（可正可负）。按 0 ~ contentHeight-height
// 夹取会让视图停在首行上方（空白），或永远够不到顶部的几行（条目“丢失”）。
// 注意：WheelHandler 不是 Item，handler 内的 parent 解析不到本视图，必须用显式 id 引用。
import QtQuick
import QtQuick.Controls

ListView {
    id: lockedList
    clip: true
    boundsBehavior: Flickable.StopAtBounds

    // 每格滚轮的滚动行数
    property int wheelLines: 3

    readonly property real minContentY: originY - topMargin
    readonly property real maxContentY: Math.max(minContentY, originY + contentHeight + bottomMargin - height)

    function boundedContentY(y) {
        return Math.max(minContentY, Math.min(maxContentY, y));
    }
    // 程序化定位（如模型刷新后恢复滚动位置）请用这个，而不是直接写 contentY
    function scrollToContentY(y) {
        wheelAnim.stop();
        contentY = boundedContentY(y);
    }

    NumberAnimation {
        id: wheelAnim
        target: lockedList
        property: "contentY"
        duration: 200
        easing.type: Easing.OutCubic
    }

    function _animateTo(target) {
        wheelAnim.stop();
        wheelAnim.to = target;
        wheelAnim.start();
    }
    // 内容尺寸或起点变化：滚轮动画进行中只修正其终点（不打断滚动），否则回到合法范围
    function _settle() {
        if (wheelAnim.running) {
            var to = boundedContentY(wheelAnim.to);
            if (to !== wheelAnim.to) _animateTo(to);
            return;
        }
        if (!moving && (contentY < minContentY - 0.5 || contentY > maxContentY + 0.5))
            contentY = boundedContentY(contentY);
    }
    onContentHeightChanged: _settle()
    onOriginYChanged: _settle()
    onHeightChanged: _settle()
    // 用户拖拽开始时停掉滚轮动画，避免争夺 contentY。
    // 注意不能用 onMovementStarted：程序化 contentY 变化（含本动画）也会触发它，
    // 会造成动画启动即自停、滚轮完全失效。
    onDragStarted: wheelAnim.stop()
    onMovementEnded: _settle()

    WheelHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: function(event) {
            var dy = event.angleDelta.y;
            if (dy !== 0) {
                var rowH = lockedList.count > 0 ? lockedList.contentHeight / lockedList.count : 32;
                var step = (dy / 120) * Math.max(48, rowH * lockedList.wheelLines);
                // 连续滚动时从上一格的终点累加，快速滚轮不会丢距离
                var from = wheelAnim.running ? wheelAnim.to : lockedList.contentY;
                var target = lockedList.boundedContentY(from - step);
                if (Math.abs(target - lockedList.contentY) > 0.5)
                    lockedList._animateTo(target);
            }
            event.accepted = true;
        }
    }
}
