// 滚动锁定的 Flickable：滚轮事件完全消费，到边界不冒泡给外层页面。
// 用法与 Flickable 完全一致（contentWidth/contentHeight/ScrollBar 等照常）。
// 滚轮为平滑动画滚动（不再一次跳半屏）；内容/视口高度变化后自动回到合法范围，避免越界空白。
// 边界以 originY 为基准（与 LockedListView 一致）。
// 注意：WheelHandler 不是 Item，handler 内的 parent 解析不到本视图，必须用显式 id 引用。
import QtQuick
import QtQuick.Controls

Flickable {
    id: lockedFlick
    clip: true
    boundsBehavior: Flickable.StopAtBounds

    // 每格滚轮滚动距离（此前一次约半屏 240px，过于突兀）
    property int wheelStep: 140

    readonly property real minContentY: originY - topMargin
    readonly property real maxContentY: Math.max(minContentY, originY + contentHeight + bottomMargin - height)

    function boundedContentY(y) {
        return Math.max(minContentY, Math.min(maxContentY, y));
    }

    NumberAnimation {
        id: wheelAnim
        target: lockedFlick
        property: "contentY"
        duration: 200
        easing.type: Easing.OutCubic
    }

    function _animateTo(target) {
        wheelAnim.stop();
        wheelAnim.to = target;
        wheelAnim.start();
    }
    // 内容尺寸变化：滚轮动画进行中只修正其终点（不打断滚动），否则回到合法范围
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
    // 用户拖拽开始时停掉滚轮动画（不能用 onMovementStarted：动画自身也会触发它）
    onDragStarted: { wheelAnim.stop(); HoverTip.hide(); }
    onMovementEnded: _settle()

    WheelHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: function(event) {
            HoverTip.hide();
            var dy = event.angleDelta.y;
            if (dy !== 0) {
                var step = (dy / 120) * lockedFlick.wheelStep;
                // 连续滚动时从上一格的终点累加，快速滚轮不会丢距离
                var from = wheelAnim.running ? wheelAnim.to : lockedFlick.contentY;
                var target = lockedFlick.boundedContentY(from - step);
                if (Math.abs(target - lockedFlick.contentY) > 0.5)
                    lockedFlick._animateTo(target);
            }
            event.accepted = true;
        }
    }
}
