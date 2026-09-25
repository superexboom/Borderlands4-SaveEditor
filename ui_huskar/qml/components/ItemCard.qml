// 物品卡片：按游戏自己的 Gameface 卡片（uiresources/item_card，最新官方补丁）翻译成 QML。
// 数据来自 core.item_card_model（与游戏 $data 同构），颜色/着色矩阵来自 item_card_theme.json；
// 渐变与边框是游戏的灰白贴图 × 稀有度着色（image://cardtint）+ 9 宫格（NineSlice）。
// 尺寸单位 rem 与游戏 CSS 一致：卡片宽 54.6rem。职业模组按社区卡片的两列技能布局。
import QtQuick

Item {
    id: card

    property var model: ({})
    property real rem: 10
    // 游戏里卡片叠在深色菜单上（顶框渐变半透明）；编辑器页面偏亮，默认垫一层深色衬底
    property bool backdrop: true
    readonly property var theme: appBridge.cardTheme
    readonly property var fonts: appBridge.cardFonts
    readonly property string root: appBridge.cardAssetRoot
    readonly property bool cjk: String(appBridge.language).indexOf("zh") === 0

    readonly property var rarity: (theme.rarity || {})[model.rarity || "common"] || ({})
    readonly property var dimTint: rarity.tint || theme.header_default_tint || [1, 1, 1]
    readonly property var brightTint: rarity.bright_tint || [1, 1, 1]
    readonly property color brightColor: rarity.bright_color || "#e4d9ce"
    readonly property color cream: "#e4d9ce"
    readonly property color blueGray: "#a0aeb1"
    readonly property color redText: "#f33a47"
    readonly property color orange: (theme.markup_colors || {}).primary || "#eb7300"
    readonly property string demi: cjk ? fonts.cjk_bold : fonts.demi
    readonly property string medium: cjk ? fonts.cjk_medium : fonts.medium
    readonly property string italic: cjk ? fonts.cjk_medium : fonts.italic
    // 没有游戏字体时回退到系统字体：用字重模拟 Industry/点黑 的 Demi 与 Medium
    readonly property bool gameFonts: !!fonts.game_fonts
    readonly property int demiWeight: gameFonts ? Font.Normal : Font.DemiBold
    readonly property int mediumWeight: gameFonts ? Font.Normal : Font.Medium

    readonly property real contentWidth: width - 4 * rem

    width: 54.6 * rem
    implicitHeight: body.y + body.height + 1.2 * rem

    function asset(rel) { return rel ? root + rel : "" }
    function tinted(rel, tint) { return rel ? "image://cardtint/" + tint[0] + "," + tint[1] + "," + tint[2] + "/" + rel : "" }
    function ui(name) { return "assets/item_card_ui/" + name }
    function hasItems(list) { return !!list && list.length > 0 }

    Rectangle {
        visible: card.backdrop
        anchors.fill: parent
        anchors.margins: -0.4 * card.rem
        radius: 0.6 * card.rem
        color: "#f00b1016"
        border.color: "#33a0aeb1"
    }

    // ------------------------------------------------------------------ //
    // background (.item_card_bkg top 2.5rem; .item_card_bkg_lines)
    // ------------------------------------------------------------------ //
    NineSlice {
        x: 0; y: 2.5 * card.rem; width: card.width; height: card.height - y
        source: card.asset(card.ui("item_card_background.png"))
        sliceLeft: 123 * 0.49; sliceRight: 123 * 0.49; sliceTop: 288 * 0.49; sliceBottom: 288 * 0.49
        widthLeft: 3.05 * card.rem; widthRight: 3.05 * card.rem; widthTop: 2 * card.rem; widthBottom: 2 * card.rem
    }
    NineSlice {
        x: 0; y: 1.5 * card.rem; width: card.width; height: card.height - y - 1 * card.rem
        source: card.asset(card.ui("item_card_background_lines.png"))
        sliceLeft: 104 * 0.49; sliceRight: 104 * 0.49; sliceTop: 158 * 0.49; sliceBottom: 158 * 0.49
        widthLeft: 2.775 * card.rem; widthRight: 2.775 * card.rem; widthTop: 4.175 * card.rem; widthBottom: 4.175 * card.rem
    }

    // ------------------------------------------------------------------ //
    // reusable pieces
    // ------------------------------------------------------------------ //
    component CardText: Text {
        color: card.blueGray
        font.family: card.medium
        font.weight: card.mediumWeight
        font.pixelSize: 2 * card.rem
        textFormat: Text.StyledText
        wrapMode: Text.Wrap
        lineHeight: 1.05
    }
    component Divider: Item {   // .item_card_section_divider: 0.2rem, margin .5rem 0
        width: card.contentWidth
        height: 1.2 * card.rem
        NineSlice {
            y: 0.5 * card.rem; width: parent.width; height: 0.2 * card.rem
            source: card.asset(card.ui("separator_separator_9slice.png"))
            sliceLeft: 64 * 0.49; sliceRight: 64 * 0.49
            widthLeft: 1.6 * card.rem; widthRight: 1.6 * card.rem
        }
    }
    component StatRow: Row {    // .item_card_primary_stats: boxes 5.5rem + dividers
        id: statRow
        property var stats: []
        width: card.contentWidth
        height: 5.5 * card.rem
        Repeater {
            model: statRow.stats
            delegate: Row {
                width: statRow.width / statRow.stats.length
                height: statRow.height
                Item {
                    width: parent.width - (index + 1 < statRow.stats.length ? 0.6 * card.rem : 0)
                    height: parent.height
                    NineSlice {
                        anchors.fill: parent
                        source: card.asset(card.ui("item_card_primary_stat_background.png"))
                        sliceLeft: 42 * 0.49; sliceRight: 42 * 0.49; sliceTop: 164 * 0.49; sliceBottom: 164 * 0.49
                        widthTop: 4.1 * card.rem; widthBottom: 4.1 * card.rem; widthLeft: 1.05 * card.rem; widthRight: 1.05 * card.rem
                    }
                    Image {
                        width: 3.25 * card.rem; height: width
                        anchors.horizontalCenter: parent.horizontalCenter
                        y: -0.5 * card.rem
                        source: card.asset(modelData.icon)
                        fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom; anchors.bottomMargin: 0.15 * card.rem
                        width: parent.width - 0.8 * card.rem
                        height: 2.8 * card.rem
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                        text: modelData.value
                        color: card.cream
                        font.family: card.demi; font.weight: card.demiWeight; font.pixelSize: 2 * card.rem
                        fontSizeMode: Text.HorizontalFit; minimumPixelSize: 1.2 * card.rem
                    }
                }
                Image {   // .primary_stat_divider 0.6rem x 2rem, translateY(-1rem)
                    visible: index + 1 < statRow.stats.length
                    width: 0.6 * card.rem; height: 2 * card.rem
                    y: (parent.height - height) / 2 - 1 * card.rem
                    source: card.asset(card.ui("stat_divider.png")); fillMode: Image.PreserveAspectFit
                }
            }
        }
    }
    component Bullet: Row {     // .item_card_secondary_stats_enhance: bullet + 2rem text
        property string text
        spacing: 1 * card.rem
        width: card.contentWidth
        Item {
            width: 1 * card.rem; height: bulletText.height
            Image {
                anchors.centerIn: parent
                width: 0.4 * card.rem; height: 2 * card.rem
                source: card.asset(card.ui("item_card_enhancement_bullet.png")); fillMode: Image.PreserveAspectFit
            }
        }
        CardText { id: bulletText; width: parent.width - 2 * card.rem; text: parent.text }
    }

    // ------------------------------------------------------------------ //
    // body
    // ------------------------------------------------------------------ //
    Column {
        id: body
        x: 2 * card.rem
        width: card.contentWidth

        // ---------------- header ----------------
        Item {
            id: header
            width: parent.width
            height: Math.max(9.5 * card.rem, titleBlock.y + titleBlock.height + 1 * card.rem)

            Rectangle {   // .item_card_header_top_fui (white x dim tint)
                x: 1 * card.rem; width: parent.width - 2 * card.rem; height: 0.2 * card.rem
                color: Qt.rgba(card.dimTint[0], card.dimTint[1], card.dimTint[2], 1)
            }
            NineSlice {   // .item_card_rarity_gradient (dim tint, opacity .7)
                width: 50.1 * card.rem
                x: (parent.width - width) / 2; y: 0.5 * card.rem
                height: parent.height - 1.25 * card.rem
                opacity: 0.7
                source: card.tinted(card.ui("item_card_header_background_2.png"), card.dimTint)
                sliceLeft: 1002 * 0.49; sliceRight: 1002 * 0.49; sliceTop: 190 * 0.30; sliceBottom: 190 * 0.30
                widthTop: 2.85 * card.rem; widthRight: 25.05 * card.rem; widthBottom: 2.85 * card.rem; widthLeft: 24.5 * card.rem
            }
            NineSlice {   // .item_card_rarity_fui (bright tint)
                x: -0.65 * card.rem; width: parent.width + 1.3 * card.rem; height: parent.height
                source: card.tinted(card.ui("item_card_header_FUI.png"), card.brightTint)
                sliceLeft: 126 * 0.49; sliceRight: 126 * 0.49; sliceTop: 168 * 0.49; sliceBottom: 168 * 0.49
                widthTop: 4.2 * card.rem; widthBottom: 4.2 * card.rem; widthLeft: 3.15 * card.rem; widthRight: 3.15 * card.rem
            }
            Image {       // .ic_pearl_texture (pearl only): 46.15 x 6.1rem, bottom .75rem
                visible: card.model.rarity === "pearl"
                width: 46.15 * card.rem; height: 6.1 * card.rem
                x: (parent.width - width) / 2; y: parent.height - 0.75 * card.rem - height
                source: visible ? card.asset(card.ui("ui_art_pearl_texture_itemcard.png")) : ""
                fillMode: Image.PreserveAspectFit; smooth: true
            }
            Image {       // .ic_header_manufacturer_bkg: 11.7 x 7.6rem, right .25rem, bottom .7rem
                visible: !!card.model.manufacturer
                width: 11.7 * card.rem; height: 7.6 * card.rem
                x: parent.width - 0.25 * card.rem - width; y: parent.height - 0.7 * card.rem - height
                source: visible ? card.asset(card.ui("ui_art_manu_itemcard_logomark_" + card.model.manufacturer + ".png")) : ""
                fillMode: Image.PreserveAspectFit; smooth: true
            }
            Image {       // .item_card_thumbnail 18 x 5.5rem (class mod portrait 6.5rem, right 9rem)
                readonly property bool classmod: card.model.thumbnail_kind === "classmod"
                width: (classmod ? 6.5 : 18) * card.rem
                height: (classmod ? 6.5 : 5.5) * card.rem
                x: parent.width - (classmod ? 9 : 3) * card.rem - width
                y: classmod ? 1.5 * card.rem : 0.5 * card.rem + (parent.height - height) / 2 + 1 * card.rem
                source: card.asset(card.model.thumbnail)
                fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true
            }
            Text {        // level: right 1rem, top .5rem, 2.4rem demi cream
                anchors.right: parent.right; anchors.rightMargin: 1 * card.rem
                y: 1 * card.rem
                text: card.model.level_text || ""
                color: card.cream
                font.family: card.demi; font.weight: card.demiWeight; font.pixelSize: 2.4 * card.rem
            }
            Column {
                id: titleBlock
                x: 0.8 * card.rem; y: 1 * card.rem
                width: 36 * card.rem
                Text {    // .item_card_name 2.4rem, line-height 110%
                    width: parent.width
                    text: card.model.name || ""
                    color: card.cream
                    font.family: card.demi; font.weight: card.demiWeight; font.pixelSize: 2.4 * card.rem
                    lineHeight: 1.1
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }
                Row {     // .ic_rarity_type_cntr: pips 4.5 x 1rem + type label 2rem (rarity bright)
                    topPadding: 0.25 * card.rem
                    bottomPadding: 0.5 * card.rem
                    spacing: 0.4 * card.rem
                    Image {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 4.5 * card.rem; height: 1 * card.rem
                        source: card.tinted(card.ui(({ common: "rarity_pip_01_common.png", uncommon: "rarity_pip_02_uncommon.png",
                                                       rare: "rarity_pip_03_rare.png", epic: "rarity_pip_04_epic.png",
                                                       legendary: "rarity_pip_05_legendary.png", pearl: "rarity_pip_06_pearl.png"
                                                     })[card.model.rarity || "common"]), card.model.rarity === "pearl" ? [1, 1, 1] : card.brightTint)
                        fillMode: Image.PreserveAspectFit; smooth: true
                    }
                    Text {
                        text: card.model.type_label || ""
                        color: card.brightColor
                        font.family: card.medium; font.weight: card.mediumWeight; font.pixelSize: 2 * card.rem
                    }
                }
                Item {    // .ic_dps_cntr: backing 3.5rem, value 2.6rem + gray sub text 2rem
                    visible: !!card.model.headline
                    width: headlineRow.width + 3 * card.rem
                    height: visible ? 3.6 * card.rem : 0
                    NineSlice {
                        anchors.fill: parent
                        source: card.asset(card.ui("item_card_dps_backing.png"))
                        sliceLeft: 65 * 0.50; sliceRight: 65 * 0.49; sliceTop: 68 * 0.49; sliceBottom: 68 * 0.49
                        widthLeft: 1.7 * card.rem; widthRight: 1.7 * card.rem; widthTop: 1.625 * card.rem; widthBottom: 1.625 * card.rem
                    }
                    Row {
                        id: headlineRow
                        x: 1.5 * card.rem
                        anchors.bottom: parent.bottom; anchors.bottomMargin: 0.4 * card.rem
                        spacing: 0.6 * card.rem
                        Text {
                            id: headlineValue
                            text: card.model.headline ? card.model.headline.value : ""
                            color: card.cream
                            font.family: card.demi; font.weight: card.demiWeight; font.pixelSize: 2.6 * card.rem
                        }
                        Text {
                            anchors.baseline: headlineValue.baseline
                            text: card.model.headline ? card.model.headline.label : ""
                            color: card.blueGray
                            font.family: card.medium; font.weight: card.mediumWeight; font.pixelSize: 2 * card.rem
                        }
                    }
                }
            }
        }

        // ---------------- primary / tertiary stats ----------------
        Item { width: 1; height: card.hasItems(card.model.primary) ? 1 * card.rem : 0 }
        StatRow { visible: card.hasItems(card.model.primary); stats: card.model.primary || [] }
        Item { width: 1; height: card.hasItems(card.model.primary) ? 0.5 * card.rem : 0 }
        Item { width: 1; height: card.hasItems(card.model.tertiary) ? 1 * card.rem : 0 }
        StatRow { visible: card.hasItems(card.model.tertiary); stats: card.model.tertiary || [] }
        Item { width: 1; height: card.hasItems(card.model.tertiary) ? 0.5 * card.rem : 0 }

        // ---------------- element (.item_card_elem_damage_cntr: 4rem, margin .5rem 1rem) ----------------
        Item {
            visible: !!card.model.element
            width: parent.width
            height: visible ? 5 * card.rem : 0
            NineSlice {
                x: 1 * card.rem; y: 0.5 * card.rem; width: parent.width - 2 * card.rem; height: 4 * card.rem
                source: card.model.element ? card.asset(card.model.element.backing) : ""
                sliceLeft: 40 * 0.49; sliceRight: 40 * 0.49; sliceTop: 23 * 0.49; sliceBottom: 23 * 0.49
                widthLeft: 1 * card.rem; widthRight: 1 * card.rem; widthTop: 0.575 * card.rem; widthBottom: 0.575 * card.rem
            }
            Row {
                anchors.centerIn: parent
                spacing: 0.5 * card.rem
                Repeater {
                    model: card.model.element ? card.model.element.icons : []
                    delegate: Item {
                        width: 3 * card.rem; height: 3 * card.rem
                        anchors.verticalCenter: parent.verticalCenter
                        Image {   // .damagetype.frame (grey tint, opacity .5)
                            anchors.fill: parent
                            opacity: (card.theme.element_frame || {}).opacity || 0.5
                            source: card.tinted(card.ui("ico_ui_art_elemental_frame.png"),
                                                (card.theme.element_frame || {}).tint || [0.62, 0.68, 0.69])
                            fillMode: Image.PreserveAspectFit; smooth: true
                        }
                        Image {
                            anchors.fill: parent
                            source: card.asset(modelData)
                            fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true
                        }
                    }
                }
                Item { width: 0.5 * card.rem; height: 1 }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: card.model.element ? card.model.element.text : ""
                    color: card.model.element ? card.model.element.color : card.cream
                    font.family: card.medium; font.weight: card.mediumWeight; font.pixelSize: 2.2 * card.rem
                }
            }
        }

        // ---------------- class mod (community two-column layout) ----------------
        Column {
            visible: !!card.model.classmod
            width: parent.width
            spacing: 1 * card.rem
            topPadding: visible ? 0.5 * card.rem : 0
            Repeater {
                model: card.model.classmod ? card.model.classmod.skills : []
                delegate: Row {
                    id: skillRow
                    readonly property var tree: (card.theme.classmod_trees || {})[modelData.tree] || ({})
                    width: parent.width
                    spacing: 1 * card.rem
                    Column {   // left: skill name above icon + points
                        width: 11 * card.rem
                        spacing: 0.4 * card.rem
                        Text {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            text: modelData.name
                            color: skillRow.tree.color || card.blueGray
                            font.family: card.demi; font.weight: card.demiWeight; font.pixelSize: 1.5 * card.rem
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                        Item {
                            width: parent.width; height: 4.2 * card.rem
                            NineSlice {
                                anchors.fill: parent
                                source: card.asset(card.ui("item_card_primary_stat_background.png"))
                                sliceLeft: 42 * 0.49; sliceRight: 42 * 0.49; sliceTop: 164 * 0.49; sliceBottom: 164 * 0.49
                                widthTop: 2.46 * card.rem; widthBottom: 2.46 * card.rem; widthLeft: 0.63 * card.rem; widthRight: 0.63 * card.rem
                            }
                            Row {
                                anchors.centerIn: parent
                                spacing: 0.5 * card.rem
                                Item {
                                    width: 3.4 * card.rem; height: width
                                    anchors.verticalCenter: parent.verticalCenter
                                    Image {
                                        anchors.fill: parent
                                        source: card.tinted(card.ui("item_card_passive_icon_container.png"), skillRow.tree.backing || [0.2, 0.4, 0.6])
                                        fillMode: Image.PreserveAspectFit; smooth: true
                                    }
                                    Image {
                                        anchors.centerIn: parent
                                        width: 2.6 * card.rem; height: width
                                        source: card.tinted(modelData.icon, skillRow.tree.icon || [1, 1, 1])
                                        fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true
                                    }
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.points
                                    color: skillRow.tree.color || card.cream
                                    font.family: card.demi; font.weight: card.demiWeight; font.pixelSize: 2 * card.rem
                                }
                            }
                        }
                    }
                    Column {   // right: tree name, description, stat line
                        width: parent.width - 12 * card.rem
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 0.2 * card.rem
                        CardText {
                            visible: !!modelData.tree_name
                            width: parent.width
                            text: modelData.tree_name
                            color: skillRow.tree.color || card.blueGray
                            font.pixelSize: 1.4 * card.rem
                        }
                        CardText { width: parent.width; text: modelData.text; font.pixelSize: 1.7 * card.rem }
                        CardText {
                            visible: !!modelData.stats
                            width: parent.width
                            text: modelData.stats
                            font.pixelSize: 1.5 * card.rem
                        }
                    }
                }
            }
            Text {   // .more_jg_text
                visible: !!card.model.classmod && card.model.classmod.omitted > 0
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: "... ... ..."
                color: card.orange
                font.family: card.medium; font.weight: card.mediumWeight; font.pixelSize: 2 * card.rem
            }
            Repeater {   // legendary effects (.item_card_legendary_text)
                model: card.model.classmod ? card.model.classmod.effects : []
                delegate: CardText { width: parent.width; text: modelData }
            }
            Divider { visible: !!card.model.classmod && card.hasItems(card.model.classmod.perks) }
            Repeater {
                model: card.model.classmod ? card.model.classmod.perks : []
                delegate: Bullet {
                    text: modelData.text + (modelData.count > 1
                          ? " <font color='" + ((card.theme.markup_colors || {}).secondary || "#2d95ca") + "'>×" + modelData.count + "</font>" : "")
                }
            }
        }

        // ---------------- enhancement ----------------
        Column {
            visible: !!card.model.enhancement
            width: parent.width
            topPadding: visible ? 0.5 * card.rem : 0
            spacing: 1 * card.rem
            Repeater {   // .item_card_corestats_n_overclock
                model: card.model.enhancement ? card.model.enhancement.core : []
                delegate: Item {
                    width: parent.width
                    height: coreText.height + 2 * card.rem
                    NineSlice {
                        anchors.fill: parent
                        source: card.asset(card.ui("item_card_primary_stat_background.png"))
                        sliceLeft: 42 * 0.49; sliceRight: 42 * 0.49; sliceTop: 164 * 0.49; sliceBottom: 164 * 0.49
                        widthTop: 4.1 * card.rem; widthBottom: 4.1 * card.rem; widthLeft: 1.05 * card.rem; widthRight: 1.05 * card.rem
                    }
                    Image {
                        x: 1 * card.rem; anchors.verticalCenter: parent.verticalCenter
                        width: 2 * card.rem; height: width
                        source: card.asset(card.ui("item_card_enhancement_small.png")); fillMode: Image.PreserveAspectFit
                    }
                    CardText {
                        id: coreText
                        x: 4 * card.rem; anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 5 * card.rem
                        text: modelData
                    }
                }
            }
            Column {
                width: parent.width
                spacing: 0.3 * card.rem
                Repeater {
                    model: card.model.enhancement ? card.model.enhancement.stats : []
                    delegate: Bullet { text: modelData }
                }
            }
        }

        // ---------------- augments (.item_card_secondary_stat_augment) ----------------
        Column {
            visible: card.hasItems(card.model.augments)
            width: parent.width
            topPadding: visible ? 0.5 * card.rem : 0
            spacing: 1 * card.rem
            Repeater {
                model: card.model.augments || []
                delegate: Row {
                    width: parent.width
                    spacing: 1 * card.rem
                    Item {   // .item_card_secondary_icon 5 x 5rem, 9-slice (right width 0)
                        width: 5 * card.rem; height: 5 * card.rem
                        NineSlice {
                            anchors.fill: parent
                            source: card.asset(card.ui("item_card_secondary_stat_background.png"))
                            sliceLeft: 64 * 0.49; sliceRight: 64 * 0.49; sliceTop: 64 * 0.49; sliceBottom: 64 * 0.49
                            widthTop: 1.6 * card.rem; widthBottom: 1.6 * card.rem; widthLeft: 1.6 * card.rem; widthRight: 0
                        }
                        Image {
                            anchors.centerIn: parent
                            width: 4 * card.rem; height: width
                            source: modelData.icon ? card.asset(modelData.icon) : card.asset(card.ui("item_card_enhancement_small.png"))
                            fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true
                        }
                    }
                    CardText {   // .temp_itemcard_augment_value: 2rem, min-height 5rem, centred
                        width: parent.width - 6 * card.rem
                        height: Math.max(5 * card.rem, implicitHeight)
                        verticalAlignment: Text.AlignVCenter
                        text: modelData.text
                    }
                }
            }
        }

        // ---------------- firmware ----------------
        Divider { visible: !!card.model.firmware }
        Row {
            visible: !!card.model.firmware
            width: parent.width
            height: visible ? 4.5 * card.rem : 0
            spacing: 1 * card.rem   // .firmware_section margin-left
            Item {   // .firmware_icon_cntr 5.5 x 4.5rem
                width: 5.5 * card.rem; height: 4.5 * card.rem
                Image {
                    anchors.fill: parent
                    source: card.model.firmware ? card.asset(card.model.firmware.icon) : ""
                    fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true
                }
            }
            Column {   // .firmware_section
                width: parent.width - 6.5 * card.rem
                anchors.verticalCenter: parent.verticalCenter
                spacing: 0.4 * card.rem
                Item {
                    width: parent.width - 1 * card.rem; height: fwName.height
                    Text {
                        id: fwName
                        text: card.model.firmware ? card.model.firmware.name : ""
                        color: card.blueGray
                        font.family: card.medium; font.weight: card.mediumWeight; font.pixelSize: 2.2 * card.rem
                    }
                    Text {
                        anchors.right: parent.right
                        text: card.model.firmware ? card.model.firmware.count_text : ""
                        color: card.cream
                        font.family: card.demi; font.weight: card.demiWeight; font.pixelSize: 2.2 * card.rem
                    }
                }
                Row {   // .firmware_bonus_pieces: 3 x flex, 1.2rem
                    width: parent.width - 1 * card.rem
                    height: 1.2 * card.rem
                    spacing: 1 * card.rem
                    Repeater {
                        model: 3
                        delegate: Item {
                            readonly property bool filled: !!card.model.firmware && index < card.model.firmware.level
                            width: (parent.width - 2 * card.rem) / 3; height: parent.height
                            Image {
                                visible: !parent.filled
                                anchors.fill: parent
                                opacity: 0.3
                                source: card.tinted(card.ui("large_diagonal_lines.png"), [0.6235, 0.6784, 0.6902])
                                fillMode: Image.Tile
                            }
                            NineSlice {   // glow reaches 1.1rem past the piece (.firmware_bonus_piece margins)
                                visible: parent.filled
                                anchors.fill: parent
                                anchors.margins: -1.1 * card.rem
                                source: card.tinted(card.ui("square_white_glow_9slice.png"), card.theme.firmware_piece_tint || [0.1, 0.73, 1])
                                sliceLeft: 28; sliceRight: 27.5; sliceTop: 28; sliceBottom: 27.5
                                widthLeft: 1.4 * card.rem; widthRight: 1.4 * card.rem; widthTop: 1.4 * card.rem; widthBottom: 1.4 * card.rem
                            }
                        }
                    }
                }
            }
        }

        // ---------------- red text ----------------
        Divider { visible: !!card.model.red_text }
        Text {   // .item_card_red_text_cntr: 2rem italic, padding 0 6rem
            visible: !!card.model.red_text
            width: parent.width
            leftPadding: 6 * card.rem; rightPadding: 6 * card.rem
            bottomPadding: 0.6 * card.rem
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            text: card.model.red_text || ""
            color: card.redText
            // game font: Industry-MediumItalic is already italic; fallbacks need the flag
            font.family: card.italic; font.italic: card.cjk || !card.gameFonts; font.pixelSize: 2 * card.rem
        }

        // ---------------- manufacturer footer (.item_card_stat_price_cntr) ----------------
        Item { width: 1; height: 0.4 * card.rem }
        Rectangle {
            visible: !!card.model.manufacturer
            width: parent.width
            height: visible ? 4.4 * card.rem : 0
            color: Qt.rgba(22 / 255, 111 / 255, 135 / 255, 0.3)
            Image {
                x: 0.4 * card.rem
                width: 27.85 * card.rem; height: parent.height - 0.4 * card.rem
                anchors.verticalCenter: parent.verticalCenter
                source: parent.visible ? card.asset(card.ui("ui_art_manu_itemcard_logotype_" + card.model.manufacturer + ".png")) : ""
                fillMode: Image.PreserveAspectFit; horizontalAlignment: Image.AlignLeft; smooth: true
            }
        }
    }
}
