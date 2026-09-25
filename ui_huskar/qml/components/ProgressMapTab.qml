// 游戏进度 · 地图：用游戏自带的地图贴图与发现点坐标拼出的离线地图。
// 左侧选地图（带收集进度）与图层；右侧滚轮以光标为中心缩放、拖动平移。
// 收集品标记：绿环 = 已收集（官方「已完成」图标），橙环 = 未收集；点击标记弹出信息卡可直接切换。
// 收集品列表的「地图」按钮经 vmGameProgress.focusCollectible 切到这里并居中定位（focusSerial 自增触发）。
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import QtQuick.Shapes
import HuskarUI.Basic

RowLayout {
    id: tab
    property var labels: ({})
    property var buttons: ({})
    spacing: 10

    readonly property color doneColor: "#78dba9"
    readonly property color missingColor: "#e6a439"
    readonly property color focusColor: "#4a90e2"
    readonly property color playerColor: "#2f7cf6"

    // 先绑定到 var 属性再遍历：直接在 JS 里遍历 VM 的列表属性，每访问一个元素都会重新读取整个列表
    readonly property var markers: vmGameProgress.mapMarkers
    readonly property var maps: vmGameProgress.mapList
    readonly property var layers: vmGameProgress.mapLayers
    readonly property var selected: {
        var id = vmGameProgress.focusMarkerId;
        if (!id) return null;
        for (var i = 0; i < markers.length; i++)
            if (markers[i].id === id) return markers[i];
        return null;
    }
    readonly property var currentMapRow: {
        var rows = maps;
        for (var i = 0; i < rows.length; i++)
            if (rows[i].key === vmGameProgress.currentMap) return rows[i];
        return null;
    }
    // 可见标记按状态计数（图例用）
    readonly property var stateCounts: {
        var counts = { done: 0, missing: 0, other: 0 };
        for (var i = 0; i < markers.length; i++) {
            if (markers[i].done === true) counts.done++;
            else if (markers[i].done === false) counts.missing++;
            else counts.other++;
        }
        return counts;
    }
    readonly property var layerRows: {
        var source = layers, rows = [], last = null;
        for (var i = 0; i < source.length; i++) {
            var row = source[i];
            if (row.group !== last) {
                rows.push({ header: true, group: row.group, title: row.group_title });
                last = row.group;
            }
            rows.push(row);
        }
        return rows;
    }

    function escapeHtml(value) {
        return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    function statusText(marker) {
        if (!marker) return "";
        // 联机快照读不到进度：可追踪的点位显示「未知」而不是误报未收集
        if (!vmGameProgress.progressAvailable && marker.challenge) return labels.status_unknown || "";
        if (marker.done === true) return labels.status_done || "Collected";
        if (marker.done === false) return labels.status_missing || "Missing";
        return labels.status_other || "";
    }
    function statusColor(marker) {
        if (marker && marker.done === true) return doneColor;
        if (marker && marker.done === false) return missingColor;
        return HusTheme.Primary.colorTextTertiary;
    }

    component LegendChip: Row {
        property color ring
        property string label
        property int count
        spacing: 6
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 12
            height: 12
            radius: 6
            color: "transparent"
            border.width: 2
            border.color: parent.ring
        }
        HusText {
            anchors.verticalCenter: parent.verticalCenter
            text: parent.label + " " + parent.count
            font.pixelSize: 12
            color: HusTheme.Primary.colorTextSecondary
        }
    }

    component ToolIconButton: HusIconButton {
        property string tip: ""
        type: HusButton.Type_Text
        onHoveredChanged: hovered ? HoverTip.showFor(this, tip, width / 2, height) : HoverTip.hideFor(this)
        Component.onDestruction: HoverTip.hideFor(this)
    }

    component LinkText: HusText {
        signal clicked()
        font.pixelSize: 12
        color: linkArea.containsMouse ? HusTheme.Primary.colorPrimaryHover : HusTheme.Primary.colorPrimary
        MouseArea {
            id: linkArea
            anchors.fill: parent
            anchors.margins: -4
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: parent.clicked()
        }
    }

    // ------------------------------------------------------------------ //
    // 左侧：地图列表 + 图层
    // ------------------------------------------------------------------ //
    GlassPanel {
        Layout.preferredWidth: 270
        Layout.fillHeight: true

        ColumnLayout {
            id: sideColumn
            anchors.fill: parent
            anchors.margins: 6
            spacing: 6

            ProgressCategoryList {
                objectName: "mapList"
                Layout.fillWidth: true
                Layout.preferredHeight: Math.round(sideColumn.height * 0.42)
                categories: tab.maps
                current: vmGameProgress.currentMap
                onPicked: function(key) { vmGameProgress.setCurrentMap(key); }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: HusTheme.isDark ? "#22ffffff" : "#18000000"
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 6
                Layout.rightMargin: 4
                HusText {
                    text: tab.labels.layers || "Layers"
                    font.bold: true
                    color: HusTheme.Primary.colorTextTertiary
                }
                Item { Layout.fillWidth: true }
                HusCheckBox {
                    objectName: "onlyMissing"
                    visible: vmGameProgress.progressAvailable
                    text: tab.labels.only_missing || ""
                    checked: vmGameProgress.mapOnlyMissing
                    onToggled: vmGameProgress.setMapOnlyMissing(checked)
                }
            }

            LockedListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 1
                ScrollBar.vertical: HusScrollBar { }
                model: tab.layerRows

                delegate: Item {
                    width: ListView.view.width - 8
                    height: modelData.header ? 28 : 30

                    RowLayout {
                        visible: !!modelData.header
                        anchors.fill: parent
                        anchors.leftMargin: 6
                        anchors.rightMargin: 4
                        spacing: 10
                        HusText {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignBottom
                            text: modelData.title || ""
                            font.bold: true
                            font.pixelSize: 12
                            color: HusTheme.Primary.colorTextTertiary
                        }
                        LinkText {
                            Layout.alignment: Qt.AlignBottom
                            text: tab.buttons.show_all_layers || "All"
                            onClicked: vmGameProgress.setLayerGroupVisible(modelData.group, true)
                        }
                        LinkText {
                            Layout.alignment: Qt.AlignBottom
                            text: tab.buttons.hide_all_layers || "None"
                            onClicked: vmGameProgress.setLayerGroupVisible(modelData.group, false)
                        }
                    }

                    Rectangle {
                        visible: !modelData.header
                        anchors.fill: parent
                        radius: 6
                        color: layerArea.containsMouse ? (HusTheme.isDark ? "#14ffffff" : "#0c000000") : "transparent"

                        MouseArea {
                            id: layerArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: vmGameProgress.setLayerVisible(modelData.key, !modelData.visible)
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 4
                            anchors.rightMargin: 6
                            spacing: 6
                            HusCheckBox {
                                checked: !!modelData.visible
                                onToggled: vmGameProgress.setLayerVisible(modelData.key, checked)
                            }
                            Image {
                                Layout.preferredWidth: 20
                                Layout.preferredHeight: 20
                                source: modelData.icon || ""
                                sourceSize: Qt.size(40, 40)
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                opacity: modelData.visible ? 1 : 0.45
                            }
                            HusText {
                                Layout.fillWidth: true
                                text: modelData.title || ""
                                elide: Text.ElideRight
                                color: modelData.visible ? HusTheme.Primary.colorTextBase : HusTheme.Primary.colorTextTertiary
                            }
                            HusText {
                                text: modelData.tracked > 0 ? modelData.done + "/" + modelData.tracked : String(modelData.count)
                                font.pixelSize: 12
                                color: modelData.tracked > 0 && modelData.done >= modelData.tracked
                                       ? tab.doneColor : HusTheme.Primary.colorTextSecondary
                            }
                        }
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------------ //
    // 右侧：地图视图
    // ------------------------------------------------------------------ //
    GlassPanel {
        Layout.fillWidth: true
        Layout.fillHeight: true

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                spacing: 14
                HusText {
                    text: tab.currentMapRow ? tab.currentMapRow.title : ""
                    font.bold: true
                    font.pixelSize: 16
                }
                LegendChip {
                    visible: vmGameProgress.progressAvailable
                    ring: tab.doneColor; label: tab.labels.legend_done || ""; count: tab.stateCounts.done
                }
                LegendChip {
                    visible: vmGameProgress.progressAvailable
                    ring: tab.missingColor; label: tab.labels.legend_missing || ""; count: tab.stateCounts.missing
                }
                LegendChip {
                    visible: vmGameProgress.progressAvailable
                    ring: "transparent"; label: tab.labels.legend_other || ""; count: tab.stateCounts.other
                }
                Row {
                    visible: !!vmGameProgress.livePlayer.on_map
                    spacing: 6
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 12
                        height: 12
                        radius: 6
                        color: tab.playerColor
                        border.width: 2
                        border.color: "white"
                    }
                    HusText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: tab.labels.legend_player || ""
                        font.pixelSize: 12
                        color: HusTheme.Primary.colorTextSecondary
                    }
                }
                Item { Layout.fillWidth: true }
                HusText {
                    text: tab.labels.zoom_hint || ""
                    font.pixelSize: 12
                    color: HusTheme.Primary.colorTextTertiary
                }
                Row {
                    spacing: 2
                    ToolIconButton {
                        objectName: "locatePlayer"
                        visible: vmGameProgress.liveMode
                        iconSource: HusIcon.AimOutlined
                        tip: vmGameProgress.livePlayer.available ? (tab.buttons.locate_player || "")
                                                                  : (tab.labels.teleport_no_position || "")
                        onClicked: {
                            if (!vmGameProgress.focusPlayer())
                                vmGameProgress.refreshLivePosition();
                        }
                    }
                    ToolIconButton {
                        iconSource: HusIcon.ZoomOutOutlined
                        tip: tab.buttons.zoom_out || ""
                        onClicked: viewer.zoomAt(viewer.zoom / 1.5, viewer.width / 2, viewer.height / 2)
                    }
                    ToolIconButton {
                        iconSource: HusIcon.ZoomInOutlined
                        tip: tab.buttons.zoom_in || ""
                        onClicked: viewer.zoomAt(viewer.zoom * 1.5, viewer.width / 2, viewer.height / 2)
                    }
                    ToolIconButton {
                        iconSource: HusIcon.ExpandOutlined
                        tip: tab.buttons.zoom_fit || ""
                        onClicked: viewer.fit()
                    }
                }
            }

            Rectangle {
                id: viewport
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 8
                color: "#0b0e13"
                clip: true

                Flickable {
                    id: viewer
                    objectName: "mapViewer"
                    anchors.fill: parent
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    contentWidth: Math.max(width, mapLayer.width)
                    contentHeight: Math.max(height, mapLayer.height)

                    property real zoom: 0.2
                    // 视图处于「适应窗口」状态时随窗口尺寸重新适配
                    property bool fitted: true
                    property bool pendingFocus: false
                    readonly property real baseW: mapImage.sourceSize.width > 0 ? mapImage.sourceSize.width : 2048
                    readonly property real baseH: mapImage.sourceSize.height > 0 ? mapImage.sourceSize.height : 2048
                    readonly property real fitZoom: Math.max(0.01, Math.min(width / baseW, height / baseH))
                    readonly property real maxZoom: fitZoom * 8
                    // 标记随缩放略微变大，但保持在可点击且不遮挡地图的范围
                    readonly property int markerSize: Math.round(Math.max(18, Math.min(28, 18 * Math.pow(zoom / fitZoom, 0.35))))
                    readonly property int focusSerial: vmGameProgress.focusSerial

                    function clampView() {
                        contentX = Math.max(0, Math.min(contentX, contentWidth - width));
                        contentY = Math.max(0, Math.min(contentY, contentHeight - height));
                    }
                    function fit() {
                        zoom = fitZoom;
                        fitted = true;
                        contentX = 0;
                        contentY = 0;
                    }
                    // 以视图坐标 (vx, vy) 为锚点缩放：锚点下的地图位置保持不动
                    function zoomAt(target, vx, vy) {
                        target = Math.max(fitZoom, Math.min(maxZoom, target));
                        if (Math.abs(target - zoom) < 1e-6) return;
                        var mx = (contentX + vx - mapLayer.x) / mapLayer.width;
                        var my = (contentY + vy - mapLayer.y) / mapLayer.height;
                        zoom = target;
                        fitted = target <= fitZoom + 1e-6;
                        contentX = mapLayer.x + mx * mapLayer.width - vx;
                        contentY = mapLayer.y + my * mapLayer.height - vy;
                        clampView();
                    }
                    // 定位目标：选中的标记（收集品列表「地图」按钮）或 live 玩家位置（「定位玩家」）
                    property bool pendingPlayer: false
                    readonly property int playerSerial: vmGameProgress.playerFocusSerial

                    function tryFocus() {
                        if ((!pendingFocus && !pendingPlayer) || width <= 0 || height <= 0) return;
                        if (mapImage.status !== Image.Ready || String(mapImage.source) !== vmGameProgress.mapImage) return;
                        var target = null;
                        if (pendingPlayer) {
                            var player = vmGameProgress.livePlayer;
                            if (player.on_map) target = player;
                        } else {
                            target = tab.selected;
                        }
                        pendingFocus = false;
                        pendingPlayer = false;
                        if (!target) return;
                        zoom = Math.max(zoom, Math.min(maxZoom, fitZoom * 3));
                        fitted = false;
                        contentX = mapLayer.x + target.u * mapLayer.width - width / 2;
                        contentY = mapLayer.y + target.v * mapLayer.height - height / 2;
                        clampView();
                    }

                    onFitZoomChanged: {
                        if (fitted || zoom < fitZoom) fit();
                        else clampView();
                    }
                    onFocusSerialChanged: { pendingFocus = true; Qt.callLater(tryFocus); }
                    onPlayerSerialChanged: { pendingPlayer = true; Qt.callLater(tryFocus); }
                    onWidthChanged: if (pendingFocus || pendingPlayer) Qt.callLater(tryFocus)
                    onDragStarted: HoverTip.hide()
                    Component.onCompleted: {
                        // 标签页首次创建前已点过「地图」按钮：补一次定位
                        if (vmGameProgress.focusSerial > 0 && vmGameProgress.focusMarkerId) pendingFocus = true;
                    }

                    // 声明在 Flickable 内会挂到 contentItem 上：先于 Flickable 自身拿到滚轮事件，
                    // point.position 是内容坐标，需减去 contentX/Y 换算成视图坐标。
                    WheelHandler {
                        id: zoomWheel
                        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                        onWheel: function(event) {
                            HoverTip.hide();
                            var steps = event.angleDelta.y / 120;
                            if (steps !== 0) {
                                var p = zoomWheel.point.position;
                                viewer.zoomAt(viewer.zoom * Math.pow(1.25, steps), p.x - viewer.contentX, p.y - viewer.contentY);
                            }
                            event.accepted = true;
                        }
                    }

                    Item {
                        id: mapLayer
                        objectName: "mapLayer"
                        x:Math.max(0, (viewer.width - width) / 2)
                        y: Math.max(0, (viewer.height - height) / 2)
                        width: viewer.baseW * viewer.zoom
                        height: viewer.baseH * viewer.zoom

                        Image {
                            id: mapImage
                            anchors.fill: parent
                            source: vmGameProgress.mapImage
                            asynchronous: true
                            smooth: true
                            mipmap: true
                            fillMode: Image.Stretch
                            onStatusChanged: {
                                if (status !== Image.Ready) return;
                                viewer.fit();
                                viewer.tryFocus();
                            }
                        }

                        Repeater {
                            model: mapImage.status === Image.Ready ? tab.markers : []

                            delegate: Item {
                                id: marker
                                readonly property bool isFocus: modelData.id === vmGameProgress.focusMarkerId
                                readonly property bool isDone: modelData.done === true
                                readonly property bool tracked: modelData.done === true || modelData.done === false
                                readonly property string iconUrl: isDone ? (modelData.icon_done_url || modelData.icon_url)
                                                                         : (modelData.icon_url || modelData.icon_done_url)
                                width: viewer.markerSize
                                height: width
                                x: modelData.u * mapLayer.width - width / 2
                                y: modelData.v * mapLayer.height - height / 2
                                z: isFocus ? 3 : (tracked && !isDone ? 2 : 1)

                                Rectangle {
                                    id: pulseRing
                                    visible: marker.isFocus
                                    anchors.centerIn: parent
                                    width: parent.width + 4
                                    height: width
                                    radius: width / 2
                                    color: "transparent"
                                    border.width: 2
                                    border.color: tab.focusColor
                                    ParallelAnimation {
                                        running: marker.isFocus
                                        loops: Animation.Infinite
                                        NumberAnimation { target: pulseRing; property: "scale"; from: 1; to: 2.2; duration: 1100; easing.type: Easing.OutCubic }
                                        NumberAnimation { target: pulseRing; property: "opacity"; from: 0.9; to: 0; duration: 1100; easing.type: Easing.OutCubic }
                                    }
                                }
                                Rectangle {
                                    anchors.centerIn: parent
                                    width: parent.width + 4
                                    height: width
                                    radius: width / 2
                                    color: "#b30b0e13"
                                    border.width: marker.tracked || marker.isFocus ? 2 : 0
                                    border.color: marker.isFocus ? tab.focusColor : (marker.isDone ? tab.doneColor : tab.missingColor)
                                }
                                Image {
                                    id: markerIcon
                                    anchors.centerIn: parent
                                    width: parent.width - 4
                                    height: width
                                    source: marker.iconUrl
                                    sourceSize: Qt.size(64, 64)
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true
                                    mipmap: true
                                    opacity: marker.isDone ? 0.8 : 1
                                }
                                Rectangle {
                                    visible: !marker.iconUrl
                                    anchors.centerIn: parent
                                    width: Math.round(parent.width * 0.4)
                                    height: width
                                    radius: width / 2
                                    color: "#cfd6e0"
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    anchors.margins: -2
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onEntered: HoverTip.showFor(marker, "<b>" + tab.escapeHtml(modelData.title) + "</b><br>"
                                                                + tab.escapeHtml(modelData.type_title)
                                                                + (marker.tracked ? " · " + tab.statusText(modelData) : ""),
                                                                mouseX, mouseY)
                                    onExited: HoverTip.hideFor(marker)
                                    onClicked: vmGameProgress.selectMarker(modelData.id)
                                }
                                Component.onDestruction: HoverTip.hideFor(marker)
                            }
                        }

                        // live 玩家位置：蓝点 + 朝向箭头（heading 由 yaw 投影到地图得到）
                        Item {
                            id: playerMarker
                            objectName: "playerMarker"
                            readonly property var player: vmGameProgress.livePlayer
                            visible: mapImage.status === Image.Ready && !!player.on_map
                            width: 18
                            height: 18
                            x: (player.u || 0) * mapLayer.width - width / 2
                            y: (player.v || 0) * mapLayer.height - height / 2
                            z: 10

                            Rectangle {
                                id: playerHalo
                                anchors.centerIn: parent
                                width: parent.width * 2.4
                                height: width
                                radius: width / 2
                                color: tab.playerColor
                                opacity: 0.25
                                SequentialAnimation on opacity {
                                    running: playerMarker.visible
                                    loops: Animation.Infinite
                                    NumberAnimation { from: 0.35; to: 0.08; duration: 1200; easing.type: Easing.InOutSine }
                                    NumberAnimation { from: 0.08; to: 0.35; duration: 1200; easing.type: Easing.InOutSine }
                                }
                            }
                            Shape {
                                // 朝向箭头：三角形底边藏在圆点下，尖端伸出右侧；整体按 heading 旋转（0° 指向右，顺时针）
                                anchors.fill: parent
                                rotation: playerMarker.player.heading || 0
                                preferredRendererType: Shape.CurveRenderer
                                ShapePath {
                                    fillColor: tab.playerColor
                                    strokeColor: "white"
                                    strokeWidth: 1.5
                                    startX: playerMarker.width + 9
                                    startY: playerMarker.height / 2
                                    PathLine { x: playerMarker.width - 3; y: playerMarker.height / 2 - 6 }
                                    PathLine { x: playerMarker.width - 3; y: playerMarker.height / 2 + 6 }
                                    PathLine { x: playerMarker.width + 9; y: playerMarker.height / 2 }
                                }
                            }
                            Rectangle {
                                anchors.fill: parent
                                radius: width / 2
                                color: tab.playerColor
                                border.width: 2.5
                                border.color: "white"
                            }
                            MouseArea {
                                anchors.fill: parent
                                hoverEnabled: true
                                onEntered: HoverTip.showFor(playerMarker, "<b>" + tab.escapeHtml(tab.labels.legend_player || "") + "</b><br>"
                                                            + "X " + Math.round(playerMarker.player.x || 0)
                                                            + " · Y " + Math.round(playerMarker.player.y || 0)
                                                            + " · Z " + Math.round(playerMarker.player.z || 0), mouseX, mouseY)
                                onExited: HoverTip.hideFor(playerMarker)
                            }
                            Component.onDestruction: HoverTip.hideFor(playerMarker)
                        }
                    }
                }

                // 选中标记的信息卡
                Rectangle {
                    id: card
                    objectName: "markerCard"
                    visible: !!tab.selected
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.margins: 12
                    width: Math.min(360, viewport.width - 24)
                    height: cardColumn.implicitHeight + 24
                    radius: 10
                    color: HusTheme.isDark ? "#eb1e2127" : "#f5ffffff"
                    border.color: HusTheme.isDark ? "#606a7b" : "#bac2ce"

                    // 吞掉卡片上的点击/拖动，避免穿透到地图
                    MouseArea { anchors.fill: parent }

                    ColumnLayout {
                        id: cardColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 12
                        spacing: 8

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Image {
                                Layout.preferredWidth: 32
                                Layout.preferredHeight: 32
                                Layout.alignment: Qt.AlignTop
                                source: tab.selected ? (tab.selected.done === true
                                                        ? (tab.selected.icon_done_url || tab.selected.icon_url)
                                                        : (tab.selected.icon_url || tab.selected.icon_done_url)) : ""
                                sourceSize: Qt.size(64, 64)
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                HusText {
                                    Layout.fillWidth: true
                                    text: tab.selected ? tab.selected.title : ""
                                    font.bold: true
                                    wrapMode: Text.Wrap
                                }
                                HusText {
                                    Layout.fillWidth: true
                                    text: tab.selected ? tab.selected.type_title : ""
                                    font.pixelSize: 12
                                    color: HusTheme.Primary.colorTextTertiary
                                    elide: Text.ElideRight
                                }
                            }
                            HusIconButton {
                                Layout.alignment: Qt.AlignTop
                                type: HusButton.Type_Text
                                iconSource: HusIcon.CloseOutlined
                                onClicked: vmGameProgress.selectMarker("")
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Rectangle {
                                width: 10
                                height: 10
                                radius: 5
                                color: tab.statusColor(tab.selected)
                            }
                            HusText {
                                Layout.fillWidth: true
                                text: tab.statusText(tab.selected)
                                color: tab.statusColor(tab.selected)
                            }
                            HusButton {
                                objectName: "markerToggle"
                                // 联机：只能把未收集的点记入游戏
                                visible: !!(tab.selected && tab.selected.stat)
                                         && (!vmGameProgress.liveMode || (vmGameProgress.liveCollect && tab.selected.done !== true))
                                enabled: (vmGameProgress.editable || vmGameProgress.liveCollect) && !appBridge.liveBusy
                                type: tab.selected && tab.selected.done === true ? HusButton.Type_Default : HusButton.Type_Primary
                                text: tab.selected && tab.selected.done === true ? (tab.buttons.mark_missing || "")
                                                                                 : (tab.buttons.mark_collected || "")
                                onClicked: vmGameProgress.setMarkerCollected(tab.selected.stat, tab.selected.done !== true)
                            }
                        }

                        // live：传送到该点（bl4_live teleport_position；仅限玩家所在地图）
                        RowLayout {
                            Layout.fillWidth: true
                            visible: vmGameProgress.liveMode
                            spacing: 8
                            HusText {
                                Layout.fillWidth: true
                                text: vmGameProgress.teleportHint
                                visible: text !== ""
                                font.pixelSize: 12
                                color: HusTheme.Primary.colorTextTertiary
                                wrapMode: Text.Wrap
                            }
                            Item { Layout.fillWidth: true; visible: vmGameProgress.teleportHint === "" }
                            HusIconButton {
                                objectName: "teleportButton"
                                type: HusButton.Type_Primary
                                iconSource: HusIcon.EnvironmentOutlined
                                text: tab.buttons.teleport || ""
                                enabled: vmGameProgress.teleportReady && !appBridge.liveBusy
                                onClicked: vmGameProgress.teleportToMarker(tab.selected.id)
                            }
                        }
                    }
                }
            }
        }
    }
}
