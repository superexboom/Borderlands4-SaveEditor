import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import QtQuick.Effects
import HuskarUI.Basic
import "components"
import "pages"

HusWindow {
    id: window
    width: 1480
    height: 900
    minimumWidth: 1024
    minimumHeight: 640
    visible: true
    color: "transparent"
    title: appBridge.windowTitle

    property bool navigationExpanded: true

    // QML does not track arbitrary Python method calls as binding
    // dependencies. Read the language property first so every top-level
    // label re-evaluates when AppBridge emits languageChanged.
    function tr(path) {
        var language = appBridge.language;
        return appBridge.trText(path);
    }
    function trFormat(path, params) {
        var language = appBridge.language;
        return appBridge.trFormat(path, params);
    }

    Component.onCompleted: {
        HoverTip.parent = Overlay.overlay;
        // 设计 token 对齐主线 core/theme_manager.py：
        // 蓝色强调 #4a90e2、Microsoft YaHei UI、深色磨砂玻璃默认
        HusTheme.installThemePrimaryColorBase("#4a90e2");
        HusTheme.installThemeColorTextBase("#1a1a24|#e8e8ec");
        HusTheme.installThemeColorBgBase("#f4f5f7|#14171c");
        HusTheme.installThemePrimaryFontSizeBase(14);
        HusTheme.installThemePrimaryFontFamiliesBase("Microsoft YaHei UI, PingFang SC, Helvetica Neue, Segoe UI, sans-serif");
        HusTheme.installThemePrimaryRadiusBase(8);
        HusTheme.installThemePrimaryAnimationBase(120, 180, 260);
        HusTheme.animationEnabled = appBridge.animations;
        HusTheme.darkMode = appBridge.dark ? HusTheme.Dark : HusTheme.Light;
        // 标题栏加高到主线 headerBar 量级（标题+副标题两行 + 大按钮）
        captionBar.height = 52;
        captionBar.winTitleDelegate = titleCapsule;
        captionBar.winExtraButtonsDelegate = extraButtons;
        if (!setSpecialEffect(HusWindow.Win_MicaAlt))
            setSpecialEffect(HusWindow.None);
    }

    // 标题栏左侧：主标题 + 副标题（对齐主线 titleLabel/subtitleLabel）+ 存档胶囊
    Component {
        id: titleCapsule
        RowLayout {
            spacing: 12
            ColumnLayout {
                spacing: 0
                Layout.alignment: Qt.AlignVCenter
                HusText {
                    text: tr("main_window.header.title")
                    font.bold: true
                    font.pixelSize: 15
                    color: HusTheme.Primary.colorTextBase
                }
                HusText {
                    text: tr("main_window.subtitle")
                    font.pixelSize: 10
                    color: HusTheme.Primary.colorTextSecondary
                    elide: Text.ElideRight
                }
            }
            Rectangle {
                visible: appBridge.fileName !== ""
                Layout.alignment: Qt.AlignVCenter
                radius: height / 2
                color: HusTheme.isDark ? "#334a90e2" : "#264a90e2"
                border.color: "#4a90e2"
                border.width: 1
                implicitWidth: Math.min(260, capText.implicitWidth + 22)
                implicitHeight: 22
                HusText {
                    id: capText
                    anchors.centerIn: parent
                    width: parent.width - 16
                    text: appBridge.fileName
                    color: HusTheme.isDark ? "#bcd6f7" : "#1c5cad"
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }

    // 标题栏右侧：操作按钮排布对齐主线 headerBar。
    // 右上角控件使用稍大的触控尺寸，避免标题栏里挤成难以点击的小图标。
    Component {
        id: extraButtons
        RowLayout {
            spacing: 10
            HusButton {
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredHeight: 36
                text: tr("main_window.header.open")
                type: HusButton.Type_Primary
                onClicked: appBridge.browseSave()
            }
            HusButton {
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredHeight: 36
                text: tr("main_window.header.save")
                enabled: appBridge.canSave
                onClicked: appBridge.save()
            }
            HusButton {
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredHeight: 36
                text: tr("main_window.header.save_as")
                enabled: appBridge.canSave
                onClicked: appBridge.saveAs()
            }
            // 语言切换沿用主线的图标按钮：当前语言通过无障碍名称和菜单选中态表达，
            // 标题栏不再放一个对非中文用户含义不明的下拉文本框。
            HusIconButton {
                id: languageButton
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: 38
                Layout.preferredHeight: 36
                iconSize: 18
                text: "🌐"
                contentDescription: trFormat("main_window.header.language", {default: "Language"})
                onClicked: {
                    var pos = languageButton.mapToItem(Overlay.overlay, 0, languageButton.height + 4)
                    languagePopup.x = Math.max(8, pos.x + languageButton.width - languagePopup.width)
                    languagePopup.y = pos.y
                    languagePopup.open()
                }
            }
            HusIconButton {
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: 38
                Layout.preferredHeight: 36
                iconSize: 18
                iconSource: appBridge.dark ? HusIcon.SunOutlined : HusIcon.MoonOutlined
                contentDescription: appBridge.dark ? tr("main_window.header.theme_light")
                                                   : tr("main_window.header.theme_dark")
                onClicked: appBridge.toggleTheme()
            }
            HusIconButton {
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: 38
                Layout.preferredHeight: 36
                iconSize: 18
                iconSource: HusIcon.SettingOutlined
                contentDescription: trFormat("main_window.settings.title", {default: "Interface Options"})
                onClicked: settingsDialog.open()
            }
            HusIconButton {
                visible: appBridge.liveActive
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: 38
                Layout.preferredHeight: 36
                iconSize: 18
                iconSource: HusIcon.ReloadOutlined
                contentDescription: "Refresh live"
                onClicked: appBridge.liveRefresh()
            }
            HusButton {
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredHeight: 36
                text: {
                    var language = appBridge.language;
                    return appBridge.liveStatusText;
                }
                type: appBridge.liveActive ? HusButton.Type_Primary : HusButton.Type_Default
                enabled: !appBridge.liveBusy
                onClicked: appBridge.toggleLive()
            }
        }
    }

    Connections {
        target: appBridge
        function onPageChanged() {
            HoverTip.hide();
            // HusMenu may drop its declarative selectedKey binding after a
            // click; force the highlight to follow programmatic navigation too.
            if (menu) menu.selectedKey = appBridge.pageKey;
            Qt.callLater(function() {
                if (menu) menu.selectedKey = appBridge.pageKey;
            });
        }
        function onThemeChanged() {
            HusTheme.darkMode = appBridge.dark ? HusTheme.Dark : HusTheme.Light;
        }
        function onAnimationsChanged() {
            HusTheme.animationEnabled = appBridge.animations;
        }
        function onToastRequested(text, kind) {
            if (kind === "error") notification.error("BL4", text, 3600);
            else if (kind === "warning") notification.warning("BL4", text, 3200);
            else if (kind === "success") message.success(text, 1800);
            else message.info(text, 1800);
        }
    }

    Popup {
        id: languagePopup
        parent: Overlay.overlay
        width: 190
        padding: 6
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            color: HusTheme.isDark ? "#F21E1E23" : "#F2FFFFFF"
            border.color: HusTheme.isDark ? "#66505060" : "#59B4B4C8"
            radius: 8
        }
        contentItem: ColumnLayout {
            spacing: 2
            Repeater {
                model: appBridge.languages
                delegate: HusButton {
                    Layout.fillWidth: true
                    text: modelData.label
                    type: modelData.value === appBridge.language
                          ? HusButton.Type_Primary : HusButton.Type_Default
                    onClicked: {
                        appBridge.setLanguage(modelData.value)
                        languagePopup.close()
                    }
                }
            }
        }
    }

    HusMessage { id: message; z: 1000; topMargin: captionBar.height + 10 }
    HusNotification { id: notification; z: 1001; position: HusNotification.Position_TopRight; topMargin: captionBar.height + 10 }

    // ---- 背景：壁纸 + 高斯模糊 + 叠加层（对齐主线 BackgroundWidget） ----
    Item {
        anchors.fill: parent
        z: -4
        Image {
            id: wallpaper
            anchors.fill: parent
            source: appBridge.backgroundUrl
            // Keep the source texture in step with the window.  The QA capture
            // tool resizes the same HusWindow instance; without an explicit
            // sourceSize MultiEffect can retain the first (small) texture until
            // the next native resize event.
            sourceSize: Qt.size(Math.max(1, width), Math.max(1, height))
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            smooth: true
            visible: false
        }
        MultiEffect {
            anchors.fill: parent
            source: wallpaper
            blurEnabled: true
            blur: 1.0
            blurMax: appBridge.blurStrength
            brightness: HusTheme.isDark ? -0.15 : 0.0
        }
        Rectangle {
            anchors.fill: parent
            color: HusTheme.isDark ? "#66000000" : "#33FFFFFF"
        }
    }

    ConfirmDialog { id: confirmDialog }
    UserIdDialog { id: userIdDialog }

    // ---- 界面调整选项 ----
    HusModal {
        id: settingsDialog
        width: 520
        closable: true
        title: trFormat("main_window.settings.title", {default: "Interface Options"})

        contentDelegate: Item {
            // Include both top and bottom padding; without the bottom reserve
            // the final theme row was laid out outside the modal background.
            implicitHeight: settingsColumn.implicitHeight + 48
            ColumnLayout {
                id: settingsColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                // HusModal 自定义 contentDelegate 不带标题栏与内边距，全部自绘
                anchors.margins: 24
                spacing: 16
                RowLayout {
                    HusText {
                        Layout.fillWidth: true
                        text: trFormat("main_window.settings.title", {default: "Interface Options"})
                        font.bold: true
                        font.pixelSize: 15
                        color: HusTheme.Primary.colorTextBase
                    }
                    HusIconButton {
                        Layout.preferredWidth: 36
                        Layout.preferredHeight: 34
                        iconSize: 17
                        iconSource: HusIcon.CloseOutlined
                        contentDescription: appBridge.trText("main_window.dialogs.cancel")
                        onClicked: settingsDialog.close()
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 4
                    Layout.rightMargin: 4
                    spacing: 4
                    HusText {
                        text: trFormat("main_window.settings.blur", {default: "Background Blur"})
                        color: HusTheme.Primary.colorTextBase
                    }
                    RowLayout {
                        spacing: 10
                        HusSlider {
                            id: blurSlider
                            Layout.fillWidth: true
                            // HusSlider 的 implicitHeight 恒为 0（vendor 尺寸链缺陷），
                            // RowLayout 不会纵向拉伸子项，必须显式给高度否则点不到
                            Layout.preferredHeight: 28
                            min: 0
                            max: 64
                            // 不用 value 绑定：拖动中 setBlurStrength 回写触发绑定重估，
                            // 会把手柄拽回已存值（表现为滑块失效/打架）。初始化一次即可。
                            Component.onCompleted: value = appBridge.blurStrength
                            onFirstMoved: appBridge.setBlurStrength(Math.round(currentValue))
                        }
                        HusText {
                            Layout.preferredWidth: 30
                            text: appBridge.blurStrength
                            color: HusTheme.Primary.colorTextSecondary
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 4
                    Layout.rightMargin: 4
                    spacing: 8
                    HusText {
                        Layout.fillWidth: true
                        text: tr("main_window.header.change_bg")
                        color: HusTheme.Primary.colorTextBase
                    }
                    HusButton {
                        Layout.preferredWidth: 112
                        Layout.preferredHeight: 34
                        text: trFormat("main_window.settings.pick_bg", {default: "Choose Image"})
                        onClicked: appBridge.changeBackground()
                    }
                    HusButton {
                        visible: appBridge.hasCustomBackground
                        Layout.preferredWidth: 88
                        Layout.preferredHeight: 34
                        text: trFormat("main_window.settings.clear_bg", {default: "Clear"})
                        onClicked: appBridge.clearBackground()
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 4
                    Layout.rightMargin: 4
                    spacing: 8
                    HusText {
                        Layout.fillWidth: true
                        text: trFormat("main_window.settings.animations", {default: "Interface Animations"})
                        color: HusTheme.Primary.colorTextBase
                    }
                    HusSwitch {
                        checked: appBridge.animations
                        onToggled: appBridge.toggleAnimations()
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 4
                    Layout.rightMargin: 4
                    spacing: 8
                    HusText {
                        Layout.fillWidth: true
                        text: appBridge.dark ? tr("main_window.header.theme_light")
                                             : tr("main_window.header.theme_dark")
                        color: HusTheme.Primary.colorTextBase
                    }
                    HusSwitch {
                        checked: appBridge.dark
                        onToggled: appBridge.toggleTheme()
                    }
                }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: captionBar.height + 8
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.bottomMargin: 10
        spacing: 10

        // ---- 主体：导航 + 页面 ----
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10

            GlassPanel {
                id: sidebar
                Layout.fillHeight: true
                Layout.preferredWidth: window.navigationExpanded ? 216 : 64

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 6
                    HusIconButton {
                        Layout.alignment: window.navigationExpanded ? Qt.AlignRight : Qt.AlignHCenter
                        iconSource: window.navigationExpanded ? HusIcon.LeftOutlined : HusIcon.RightOutlined
                        contentDescription: "navigation"
                        onClicked: window.navigationExpanded = !window.navigationExpanded
                    }
                    LockedFlickable {
                        id: menuViewport
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        implicitWidth: window.navigationExpanded ? 190 : 46
                        implicitHeight: 320
                        contentWidth: width
                        contentHeight: menu.implicitHeight
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: HusScrollBar { }
                        HusMenu {
                            id: menu
                            objectName: "mainMenu"
                            width: menuViewport.width
                            defaultMenuWidth: window.navigationExpanded ? 190 : 46
                            compactMode: window.navigationExpanded ? HusMenu.Mode_Relaxed : HusMenu.Mode_Compact
                            showToolTip: !window.navigationExpanded
                            initModel: appBridge.navigation
                            selectedKey: appBridge.pageKey
                            onClickMenu: function(deep, key, keyPath, data) { appBridge.navigate(key); }
                        }
                    }
                }
                Behavior on Layout.preferredWidth {
                    enabled: HusTheme.animationEnabled
                    NumberAnimation { duration: HusTheme.Primary.durationMid; easing.type: Easing.InOutCubic }
                }
            }

            GlassPanel {
                id: workspace
                Layout.fillWidth: true
                Layout.fillHeight: true

                Loader {
                    id: pageLoader
                    anchors.fill: parent
                    // 页面与玻璃面板边缘之间留出主线 contentWrapper 级别的内边距，
                    // 各 tab 元素不再紧贴工作区上下左右边框
                    anchors.margins: 12
                    asynchronous: true
                    source: {
                        var file = appBridge.pageFiles[appBridge.pageKey];
                        return file ? ("pages/" + file) : "";
                    }
                    onStatusChanged: if (status === Loader.Ready) {
                        Qt.callLater(function() {
                            if (pageLoader.item && pageLoader.item.fillFields)
                                pageLoader.item.fillFields();
                        });
                    }
                }
                Rectangle {
                    anchors.fill: parent
                    z: 20
                    visible: pageLoader.status !== Loader.Ready
                    color: HusTheme.isDark ? "#d914171c" : "#d9f4f5f7"
                    HusText {
                        anchors.centerIn: parent
                        text: trFormat("main_window.status.loading", {default: "Loading…"})
                        color: HusTheme.Primary.colorTextSecondary
                    }
                }
            }
        }

        // ---- Footer：自动保存 + 状态 ----
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 26
            spacing: 10
            HusCheckBox {
                id: autosaveBox
                text: (appBridge.autosaveFailed ? "⚠ " : "") + tr("main_window.status.autosave")
                checked: appBridge.autosaveEnabled
                enabled: appBridge.canSave
                contentDescription: tr("main_window.status.autosave_tip")
                onToggled: appBridge.setAutosaveEnabled(checked)
            }
            HusText {
                text: appBridge.autosaveMessage
                color: appBridge.autosaveFailed ? HusTheme.Primary.colorError : HusTheme.Primary.colorTextTertiary
                font.pixelSize: 11
            }
            Item { Layout.fillWidth: true }
            HusText {
                text: appBridge.status
                color: HusTheme.Primary.colorTextSecondary
                elide: Text.ElideMiddle
                Layout.maximumWidth: 520
            }
            HusText {
                text: "PyQt6 · HuskarUI Qt6"
                color: HusTheme.Primary.colorTextTertiary
                font.pixelSize: 11
            }
        }
    }
}
