// Main.qml supplies the window overlay explicitly; this singleton has no window of its own.
pragma Singleton
import QtQuick
import QtQuick.Controls
import HuskarUI.Basic
Popup {
    id: tip
    objectName: "hoverTip"
    property string html: ""
    property var owner: null
    property point cursor: Qt.point(0, 0)
    property int showDelay: 350
    property int minTooltipWidth: 150
    property int maxTooltipWidth: 440
    z: 9999
    padding: 12
    margins: 8
    modal: false
    focus: false
    closePolicy: Popup.NoAutoClose
    // Estimate the unwrapped line width so short labels do not get a fixed
    // 440px bubble; rich text is still wrapped against the real width below.
    property int estimatedTextWidth: {
        var plain = String(tip.html || "").replace(/<[^>]+>/g, "")
        var width = 0
        for (var i = 0; i < plain.length; i++)
            width += plain.charCodeAt(i) > 255 ? 14 : 7
        return width + 28
    }
    width: Math.min(parent ? parent.width - 16 : maxTooltipWidth,
                    Math.max(minTooltipWidth, Math.min(maxTooltipWidth, tip.estimatedTextWidth)))
    height: Math.min(tipText.implicitHeight + 24, parent ? parent.height - 16 : 600)
    background: Rectangle {
        color: HusTheme.isDark ? "#f0242831" : "#fafafcff"
        border.color: HusTheme.isDark ? "#606a7b" : "#bac2ce"
        radius: 8
    }
    contentItem: Flickable {
        clip: true
        contentHeight: tipText.implicitHeight
        contentWidth: width
        Text {
            id: tipText
            width: parent.width
            text: tip.html
            textFormat: Text.RichText
            wrapMode: Text.Wrap
            font.family: "Microsoft YaHei UI"
            font.pixelSize: 14
            color: HusTheme.Primary.colorTextBase
        }
    }
    function themeHtml(value) {
        var text = String(value || "");
        if (HusTheme.isDark) return text;
        // Class-mod legendary effects were exported with the dark-theme
        // secondary color. Keep the rich markup, but make those spans readable
        // on the light tooltip/panel background.
        return text.replace(/#d7dee8/ig, "#374151")
                   .replace(/#ffffff/ig, "#374151")
                   .replace(/#e8e8ec/ig, "#374151");
    }
    function toHtml(value) {
        var text = String(value || "");
        if (/<\/?(?:b|i|br|p|span|font|div|table|img)\b/i.test(text)) return themeHtml(text);
        return themeHtml(text.replace(/&/g, "&amp;").replace(/</g, "&lt;")
                   .replace(/>/g, "&gt;").replace(/\n/g, "<br>"));
    }
    function showFor(item, value, px, py) {
        if (!item || !tip.parent || !value) { hideFor(item); return; }
        var content = toHtml(value);
        var same = tip.owner === item && tip.html === content;
        if (same && tip.visible) return;
        tip.cursor = item.mapToItem(tip.parent, px, py);
        if (!same) {
            tip.close(); tip.owner = item; tip.html = content; delayTimer.restart();
        } else if (!delayTimer.running) delayTimer.start();
    }
    function hideFor(item) { if (tip.owner === item) hide(); }
    function hide() { delayTimer.stop(); tip.close(); tip.owner = null; tip.html = ""; }
    Timer {
        id: delayTimer
        interval: tip.showDelay
        onTriggered: {
            if (!tip.owner || !tip.owner.visible || !tip.html || !tip.parent) return;
            var px = tip.cursor.x + 18;
            var py = tip.cursor.y + 22;
            if (px + tip.width > tip.parent.width - 8) px = tip.cursor.x - tip.width - 18;
            if (py + tip.height > tip.parent.height - 8) py = tip.cursor.y - tip.height - 18;
            tip.x = Math.max(8, Math.min(px, tip.parent.width - tip.width - 8));
            tip.y = Math.max(8, Math.min(py, tip.parent.height - tip.height - 8));
            tip.open();
        }
    }
}
