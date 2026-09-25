// CSS border-image (stretch) for the item card: slices in source pixels, widths in target pixels.
// Like CSS, the widths shrink proportionally when two opposite widths exceed the box.
import QtQuick

Item {
    id: root
    property url source
    property real sliceLeft: 0
    property real sliceTop: 0
    property real sliceRight: 0
    property real sliceBottom: 0
    property real widthLeft: sliceLeft
    property real widthTop: sliceTop
    property real widthRight: sliceRight
    property real widthBottom: sliceBottom
    property bool fill: true

    readonly property real f: Math.min(1,
        (widthLeft + widthRight) > 0 ? width / (widthLeft + widthRight) : 1,
        (widthTop + widthBottom) > 0 ? height / (widthTop + widthBottom) : 1)
    readonly property real l: widthLeft * f
    readonly property real r: widthRight * f
    readonly property real t: widthTop * f
    readonly property real b: widthBottom * f

    Image { id: probe; source: root.source; visible: false }
    readonly property real sw: probe.sourceSize.width
    readonly property real sh: probe.sourceSize.height

    // image://cardtint ignores sourceClipRect, so provider sources carry the clip in the id.
    readonly property bool viaProvider: String(source).indexOf("image://") === 0

    component Piece: Image {
        property real sx
        property real sy
        property real sW
        property real sH
        source: root.viaProvider
                ? root.source + "?clip=" + [sx, sy, Math.max(1, sW), Math.max(1, sH)].map(Math.round).join(",")
                : root.source
        sourceClipRect: root.viaProvider ? Qt.rect(0, 0, 0, 0) : Qt.rect(sx, sy, Math.max(1, sW), Math.max(1, sH))
        fillMode: Image.Stretch
        smooth: true
        visible: width > 0 && height > 0 && sW > 0 && sH > 0
    }
    // corners
    Piece { x: 0; y: 0; width: root.l; height: root.t; sx: 0; sy: 0; sW: root.sliceLeft; sH: root.sliceTop }
    Piece { x: root.width - root.r; y: 0; width: root.r; height: root.t; sx: root.sw - root.sliceRight; sy: 0; sW: root.sliceRight; sH: root.sliceTop }
    Piece { x: 0; y: root.height - root.b; width: root.l; height: root.b; sx: 0; sy: root.sh - root.sliceBottom; sW: root.sliceLeft; sH: root.sliceBottom }
    Piece { x: root.width - root.r; y: root.height - root.b; width: root.r; height: root.b; sx: root.sw - root.sliceRight; sy: root.sh - root.sliceBottom; sW: root.sliceRight; sH: root.sliceBottom }
    // edges
    Piece { x: root.l; y: 0; width: root.width - root.l - root.r; height: root.t; sx: root.sliceLeft; sy: 0; sW: root.sw - root.sliceLeft - root.sliceRight; sH: root.sliceTop }
    Piece { x: root.l; y: root.height - root.b; width: root.width - root.l - root.r; height: root.b; sx: root.sliceLeft; sy: root.sh - root.sliceBottom; sW: root.sw - root.sliceLeft - root.sliceRight; sH: root.sliceBottom }
    Piece { x: 0; y: root.t; width: root.l; height: root.height - root.t - root.b; sx: 0; sy: root.sliceTop; sW: root.sliceLeft; sH: root.sh - root.sliceTop - root.sliceBottom }
    Piece { x: root.width - root.r; y: root.t; width: root.r; height: root.height - root.t - root.b; sx: root.sw - root.sliceRight; sy: root.sliceTop; sW: root.sliceRight; sH: root.sh - root.sliceTop - root.sliceBottom }
    // center
    Piece { visible: root.fill; x: root.l; y: root.t; width: root.width - root.l - root.r; height: root.height - root.t - root.b; sx: root.sliceLeft; sy: root.sliceTop; sW: root.sw - root.sliceLeft - root.sliceRight; sH: root.sh - root.sliceTop - root.sliceBottom }
}
