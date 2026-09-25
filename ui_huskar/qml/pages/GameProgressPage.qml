import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "../components"

// 游戏进度页：离线存档的进度查看与编辑（NCS 生成的 progress_catalog 提供名称与目标）
Item {
    id: page

    readonly property var loc: vmGameProgress.strings
    readonly property var labels: loc.labels || ({})
    readonly property var tabsLoc: loc.tabs || ({})
    readonly property var buttons: loc.buttons || ({})
    readonly property bool ready: vmGameProgress.saveLoaded && vmGameProgress.catalogAvailable
    readonly property int mapTabIndex: 4
    readonly property int accountTabIndex: 5
    // 打开账号存档时直接切到「账号进度」（其余页签只适用于角色存档）
    readonly property bool profileSave: vmGameProgress.saveKind === "profile"
    onProfileSaveChanged: if (profileSave) tabs.currentIndex = accountTabIndex
    // 回到本页时恢复上次的页签（页面每次导航都会重建）。HusTabView 填充模型时会把索引归零，
    // 所以延后一轮再恢复，恢复前的索引变化也不记录。
    property bool tabRestored: false
    Component.onCompleted: Qt.callLater(function() {
        tabs.currentIndex = page.profileSave ? page.accountTabIndex : Math.max(0, vmGameProgress.tabIndex);
        page.tabRestored = true;
    })
    // 联机快照读不到进度（只有地图可用），其它非角色存档（账号存档）另有提示
    readonly property string nonCharacterHint: vmGameProgress.saveKind !== "live" ? (labels.character_only || "")
                                               : vmGameProgress.liveProgressLoading ? (labels.live_progress_loading || "")
                                               : (labels.live_progress_unavailable || "")

    EmptyHint {
        anchors.fill: parent
        visible: !vmGameProgress.saveLoaded
        description: page.labels.load_save_first || ""
    }
    EmptyHint {
        anchors.fill: parent
        visible: vmGameProgress.saveLoaded && !vmGameProgress.catalogAvailable
        description: page.labels.no_catalog || ""
    }

    ColumnLayout {
        anchors.fill: parent
        visible: page.ready
        spacing: 8

        // live：进度读自游戏（只读），按需刷新；读取信息/错误显示在右侧
        RowLayout {
            Layout.fillWidth: true
            visible: vmGameProgress.liveMode
            spacing: 10
            HusText {
                Layout.fillWidth: true
                text: (vmGameProgress.liveCollect ? page.labels.live_mode_collect : page.labels.live_mode) || ""
                color: "#e6a439"
                wrapMode: Text.Wrap
            }
            HusText {
                objectName: "liveProgressInfo"
                text: vmGameProgress.liveProgressInfo
                font.pixelSize: 12
                color: HusTheme.Primary.colorTextTertiary
            }
            HusButton {
                objectName: "refreshLiveProgress"
                text: page.buttons.refresh_live || "Refresh"
                enabled: !vmGameProgress.liveProgressLoading
                onClicked: vmGameProgress.refreshLiveProgress()
            }
        }
        HusText {
            Layout.fillWidth: true
            visible: vmGameProgress.saveKind === "profile"
            text: page.labels.profile_save || ""
            color: HusTheme.Primary.colorTextSecondary
            wrapMode: Text.Wrap
        }

        HusTabView {
            id: tabs
            objectName: "progressTabs"
            Layout.fillWidth: true
            Layout.fillHeight: true
            initModel: [
                { key: "overview", title: page.tabsLoc.overview || "Overview", contentDelegate: lazyOverview },
                { key: "missions", title: page.tabsLoc.missions || "Missions", contentDelegate: lazyMissions },
                { key: "challenges", title: page.tabsLoc.challenges || "Challenges", contentDelegate: lazyChallenges },
                { key: "collectibles", title: page.tabsLoc.collectibles || "Collectibles", contentDelegate: lazyCollectibles },
                { key: "map", title: page.tabsLoc.map || "Map", contentDelegate: lazyMap },
                { key: "account", title: page.tabsLoc.profile || "Account", contentDelegate: lazyAccount }
            ]
            onCurrentIndexChanged: if (page.tabRestored) vmGameProgress.setTabIndex(currentIndex)
        }
    }

    // HusTabView 会一次性创建全部页签内容；这里改为首次切到该页签时才创建，之后保留
    component LazyTab: Loader {
        property bool seen: false
        active: seen || visible
        onVisibleChanged: if (visible) seen = true
    }
    Component { id: lazyOverview; LazyTab { sourceComponent: overviewContent } }
    Component { id: lazyMissions; LazyTab { sourceComponent: missionsContent } }
    Component { id: lazyChallenges; LazyTab { sourceComponent: challengesContent } }
    Component { id: lazyCollectibles; LazyTab { sourceComponent: collectiblesContent } }
    Component { id: lazyMap; LazyTab { sourceComponent: mapContent } }
    Component { id: lazyAccount; LazyTab { sourceComponent: accountContent } }

    Component {
        id: accountContent
        Item {
            ProgressAccountTab {
                objectName: "accountTab"
                anchors.fill: parent
                anchors.topMargin: 8
                visible: vmGameProgress.saveKind === "profile"
                labels: page.labels
                buttons: page.buttons
            }
            EmptyHint {
                anchors.fill: parent
                visible: vmGameProgress.saveKind !== "profile"
                description: page.labels.account_only || ""
            }
        }
    }

    Component {
        id: missionsContent
        Item {
            ProgressMissionsTab {
                objectName: "missionsTab"
                anchors.fill: parent
                anchors.topMargin: 8
                visible: vmGameProgress.progressAvailable
                labels: page.labels
                buttons: page.buttons
            }
            EmptyHint {
                anchors.fill: parent
                visible: !vmGameProgress.progressAvailable
                description: page.nonCharacterHint
            }
        }
    }

    Component {
        id: challengesContent
        Item {
            ProgressChallengesTab {
                anchors.fill: parent
                anchors.topMargin: 8
                visible: vmGameProgress.progressAvailable
                labels: page.labels
                buttons: page.buttons
            }
            EmptyHint {
                anchors.fill: parent
                visible: !vmGameProgress.progressAvailable
                description: page.nonCharacterHint
            }
        }
    }

    Component {
        id: mapContent
        Item {
            ProgressMapTab {
                anchors.fill: parent
                anchors.topMargin: 8
                visible: vmGameProgress.saveKind === "character" || vmGameProgress.saveKind === "live"
                labels: page.labels
                buttons: page.buttons
            }
            EmptyHint {
                anchors.fill: parent
                visible: vmGameProgress.saveKind !== "character" && vmGameProgress.saveKind !== "live"
                description: page.nonCharacterHint
            }
        }
    }

    Component {
        id: collectiblesContent
        Item {
            ProgressCollectiblesTab {
                objectName: "collectiblesTab"
                anchors.fill: parent
                anchors.topMargin: 8
                visible: vmGameProgress.progressAvailable
                labels: page.labels
                buttons: page.buttons
                mapAvailable: true
                onShowOnMap: function(stat) {
                    if (vmGameProgress.focusCollectible(stat))
                        tabs.currentIndex = page.mapTabIndex;
                }
            }
            EmptyHint {
                anchors.fill: parent
                visible: !vmGameProgress.progressAvailable
                description: page.nonCharacterHint
            }
        }
    }

    // ------------------------------------------------------------------ //
    // 概览
    // ------------------------------------------------------------------ //
    Component {
        id: overviewContent

        LockedFlickable {
            id: overviewFlick
            contentWidth: width
            contentHeight: overviewColumn.implicitHeight + 12
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: HusScrollBar { }

            ColumnLayout {
                id: overviewColumn
                width: overviewFlick.width - 2
                spacing: 10

                EmptyHint {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 80
                    visible: !vmGameProgress.progressAvailable
                    description: page.nonCharacterHint
                }

                // ---- 完成度 ----
                GridLayout {
                    Layout.fillWidth: true
                    visible: vmGameProgress.progressAvailable
                    columns: 4
                    columnSpacing: 10
                    rowSpacing: 10
                    Repeater {
                        model: vmGameProgress.summaryTiles
                        delegate: GlassPanel {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.preferredHeight: 132
                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 14
                                spacing: 12
                                HusProgress {
                                    visible: modelData.total > 0
                                    Layout.preferredWidth: 88
                                    Layout.preferredHeight: 88
                                    type: HusProgress.Type_Circle
                                    percent: modelData.total > 0 ? Math.min(100, modelData.value * 100 / modelData.total) : 0
                                    status: modelData.total > 0 && modelData.value >= modelData.total
                                            ? HusProgress.Status_Success : HusProgress.Status_Normal
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 4
                                    HusText {
                                        text: modelData.label
                                        color: HusTheme.Primary.colorTextSecondary
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                    HusText {
                                        text: modelData.total > 0 ? (modelData.value + " / " + modelData.total) : String(modelData.value)
                                        font.pixelSize: 22
                                        font.bold: true
                                        color: HusTheme.Primary.colorTextBase
                                    }
                                }
                            }
                        }
                    }
                }

                // ---- 基础数值 ----
                GlassPanel {
                    id: basics
                    Layout.fillWidth: true
                    Layout.preferredHeight: basicsColumn.implicitHeight + 32
                    visible: vmGameProgress.saveKind === "character"

                    function collect() {
                        var values = {
                            hours: hoursInput.text, minutes: minutesInput.text,
                            cash: cashInput.text, eridium: eridiumInput.text,
                            uvh_level: uvhLevelInput.text, uvh_highest: uvhHighestInput.text
                        };
                        for (var i = 0; i < ammoRepeater.count; i++) {
                            var item = ammoRepeater.itemAt(i);
                            if (item) values["ammo." + item.ammoKey] = item.valueText;
                        }
                        return values;
                    }

                    ColumnLayout {
                        id: basicsColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 16
                        spacing: 10

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            columnSpacing: 12
                            rowSpacing: 8

                            HusText { Layout.preferredWidth: 150; text: page.labels.playtime || ""; color: HusTheme.Primary.colorTextSecondary }
                            RowLayout {
                                spacing: 6
                                HusInput {
                                    id: hoursInput
                                    Layout.preferredWidth: 90
                                    text: String(vmGameProgress.playtimeHours)
                                    enabled: vmGameProgress.editable
                                    validator: IntValidator { bottom: 0; top: 999999 }
                                }
                                HusText { text: page.labels.hours || ""; color: HusTheme.Primary.colorTextSecondary }
                                HusInput {
                                    id: minutesInput
                                    Layout.preferredWidth: 64
                                    text: String(vmGameProgress.playtimeMinutes)
                                    enabled: vmGameProgress.editable
                                    validator: IntValidator { bottom: 0; top: 59 }
                                }
                                HusText { text: page.labels.minutes || ""; color: HusTheme.Primary.colorTextSecondary }
                                Item { Layout.preferredWidth: 18 }
                                HusText { text: (page.labels.last_played || "") + "：" + vmGameProgress.lastPlayedText; color: HusTheme.Primary.colorTextTertiary }
                            }

                            HusText { Layout.preferredWidth: 150; text: page.labels.uvh || ""; color: HusTheme.Primary.colorTextSecondary }
                            RowLayout {
                                spacing: 6
                                HusText { text: page.labels.uvh_level || ""; color: HusTheme.Primary.colorTextSecondary }
                                HusInput {
                                    id: uvhLevelInput
                                    Layout.preferredWidth: 64
                                    text: String(vmGameProgress.uvhLevel)
                                    enabled: vmGameProgress.editable
                                    validator: IntValidator { bottom: 0; top: vmGameProgress.uvhMax }
                                }
                                HusText { text: page.labels.uvh_highest || ""; color: HusTheme.Primary.colorTextSecondary }
                                HusInput {
                                    id: uvhHighestInput
                                    Layout.preferredWidth: 64
                                    text: String(vmGameProgress.uvhHighest)
                                    enabled: vmGameProgress.editable
                                    validator: IntValidator { bottom: 0; top: vmGameProgress.uvhMax }
                                }
                                HusText { text: "/ " + vmGameProgress.uvhMax; color: HusTheme.Primary.colorTextTertiary }
                            }

                            HusText { Layout.preferredWidth: 150; text: page.labels.currencies || ""; color: HusTheme.Primary.colorTextSecondary }
                            RowLayout {
                                spacing: 6
                                HusText { text: page.labels.cash || ""; color: HusTheme.Primary.colorTextSecondary }
                                HusInput {
                                    id: cashInput
                                    Layout.preferredWidth: 140
                                    text: vmGameProgress.cash
                                    enabled: vmGameProgress.editable
                                    validator: IntValidator { bottom: 0; top: 2147483647 }
                                }
                                HusText { text: page.labels.eridium || ""; color: HusTheme.Primary.colorTextSecondary }
                                HusInput {
                                    id: eridiumInput
                                    Layout.preferredWidth: 140
                                    text: vmGameProgress.eridium
                                    enabled: vmGameProgress.editable
                                    validator: IntValidator { bottom: 0; top: 2147483647 }
                                }
                                HusButton {
                                    text: page.buttons.max_currency || ""
                                    enabled: vmGameProgress.editable
                                    onClicked: vmGameProgress.maxCurrency()
                                }
                            }

                            HusText { Layout.preferredWidth: 150; Layout.alignment: Qt.AlignTop; text: page.labels.ammo || ""; color: HusTheme.Primary.colorTextSecondary }
                            ColumnLayout {
                                spacing: 6
                                Flow {
                                    Layout.fillWidth: true
                                    spacing: 10
                                    Repeater {
                                        id: ammoRepeater
                                        model: vmGameProgress.ammoRows
                                        delegate: RowLayout {
                                            property string ammoKey: modelData.key
                                            property alias valueText: ammoInput.text
                                            spacing: 4
                                            HusText { text: modelData.label; color: HusTheme.Primary.colorTextSecondary }
                                            HusInput {
                                                id: ammoInput
                                                Layout.preferredWidth: 80
                                                text: modelData.value
                                                enabled: vmGameProgress.editable
                                                validator: IntValidator { bottom: 0; top: 99999 }
                                            }
                                        }
                                    }
                                }
                                HusButton {
                                    text: page.buttons.fill_ammo || ""
                                    enabled: vmGameProgress.editable
                                    onClicked: vmGameProgress.fillAmmo()
                                }
                            }
                        }

                        RowLayout {
                            HusText {
                                text: page.labels.true_mode + "：" + (vmGameProgress.trueMode ? "✓" : "—")
                                color: HusTheme.Primary.colorTextTertiary
                            }
                            Item { Layout.fillWidth: true }
                            HusButton {
                                text: page.buttons.apply || "Apply"
                                type: HusButton.Type_Primary
                                enabled: vmGameProgress.editable
                                onClicked: vmGameProgress.applyOverview(basics.collect())
                            }
                        }
                    }
                }

                // ---- 各区域击杀 ----
                GlassPanel {
                    Layout.fillWidth: true
                    Layout.preferredHeight: killsColumn.implicitHeight + 32
                    visible: vmGameProgress.saveKind === "character" && vmGameProgress.regionKills.length > 0
                    ColumnLayout {
                        id: killsColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 16
                        spacing: 8
                        HusText { text: page.labels.region_kills || ""; font.bold: true; color: HusTheme.Primary.colorTextBase }
                        GridLayout {
                            Layout.fillWidth: true
                            columns: 3
                            columnSpacing: 16
                            rowSpacing: 4
                            Repeater {
                                model: vmGameProgress.regionKills
                                delegate: RowLayout {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    HusText { text: modelData.title; color: HusTheme.Primary.colorTextSecondary; elide: Text.ElideRight; Layout.fillWidth: true }
                                    HusText { text: modelData.kills; font.bold: true; color: HusTheme.Primary.colorTextBase }
                                }
                            }
                        }
                    }
                }

                HusText {
                    Layout.alignment: Qt.AlignRight
                    text: (page.labels.catalog_version || "{version}").replace("{version}", vmGameProgress.catalogVersion)
                    color: HusTheme.Primary.colorTextTertiary
                    font.pixelSize: 11
                }
            }
        }
    }
}
