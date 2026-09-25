import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "../components"
import "../components/PartColors.js" as PartColors
import "../components/CopyKeys.js" as CopyKeys

// 武器编辑器页：对齐主线 WeaponEditorTab（背包浏览 + 部件编辑）
RowLayout {
    id: page
    anchors.fill: parent
    anchors.margins: 0
    spacing: 10

    readonly property var loc: vmWeaponEditor.strings
    readonly property var labelsLoc: loc.labels || ({})
    readonly property var buttonsLoc: loc.buttons || ({})

    // 部件列表选中项（Ctrl+C 复制目标，-1 表示无）
    property int selectedPartIndex: -1

    SelectionStyle { id: selStyle }

    // ---- 左：背包武器浏览 ----
    GlassPanel {
        Layout.preferredWidth: 330
        Layout.fillHeight: true

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8
            HusText {
                text: labelsLoc.load_from_backpack || ""
                font.bold: true
                color: HusTheme.Primary.colorTextBase
            }
            HusInput {
                Layout.fillWidth: true
                placeholderText: labelsLoc.search_weapon_placeholder || ""
                onTextChanged: vmWeaponEditor.setBrowserSearch(text)
            }
            LockedListView {
                id: browserList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: HusScrollBar { }
                model: vmWeaponEditor.browserRows
                activeFocusOnTab: true

                // Ctrl+C 复制选中武器的 Base85 序列
                Keys.onPressed: function(event) {
                    if (CopyKeys.matchCopy(event))
                        vmWeaponEditor.copyBrowserSerial(browserList.currentIndex);
                }

                delegate: Item {
                    width: ListView.view.width
                    height: 96
                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 2
                        radius: 6
                        property bool selected: modelData.selected
                        color: selected ? selStyle.bg
                             : (HusTheme.isDark ? "#1AFFFFFF" : "#0D000000")
                    }
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 3
                        HusText {
                            Layout.fillWidth: true
                            text: modelData.title
                            color: modelData.selected ? selStyle.text : HusTheme.Primary.colorTextBase
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        HusText {
                            Layout.fillWidth: true
                            text: modelData.detail
                            color: modelData.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                        RowLayout {
                            spacing: 6
                            Repeater {
                                model: modelData.stats
                                delegate: Column {
                                    spacing: 0
                                    HusText {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: modelData.label
                                        color: HusTheme.Primary.colorTextTertiary
                                        font.pixelSize: 9
                                    }
                                    HusText {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: modelData.value
                                        color: HusTheme.Primary.colorTextBase
                                        font.pixelSize: 11
                                    }
                                }
                            }
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            browserList.currentIndex = index;
                            browserList.forceActiveFocus();
                            vmWeaponEditor.loadBrowserItem(index);
                        }
                    }
                }
            }
            HusText {
                Layout.fillWidth: true
                text: vmWeaponEditor.selectedSummary
                color: HusTheme.Primary.colorTextSecondary
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }
        }
    }

    // ---- 右：编辑区 ----
    LockedFlickable {
        id: editFlick
        Layout.fillWidth: true
        Layout.fillHeight: true
        contentWidth: width
        contentHeight: editColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: HusScrollBar { }
        activeFocusOnTab: true

        // Ctrl+C 复制部件列表选中行文本
        Keys.onPressed: function(event) {
            if (CopyKeys.matchCopy(event))
                vmWeaponEditor.copyPartText(page.selectedPartIndex);
        }

        ColumnLayout {
            id: editColumn
            width: parent.width - 2
            spacing: 10

            // 序列号
            GlassPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: serialColumn.implicitHeight + 28

                ColumnLayout {
                    id: serialColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    spacing: 8
                    RowLayout {
                        spacing: 8
                        HusText { Layout.preferredWidth: 86; text: labelsLoc.serial_b85 || "Base85:"; color: HusTheme.Primary.colorTextSecondary }
                        HusInput {
                            Layout.fillWidth: true
                            text: vmWeaponEditor.b85Text
                            readOnly: vmWeaponEditor.b85Readonly
                            onEditingFinished: vmWeaponEditor.setB85Text(text)
                        }
                    }
                    RowLayout {
                        spacing: 8
                        HusText { Layout.preferredWidth: 86; text: labelsLoc.serial_decoded || "Deserialize:"; color: HusTheme.Primary.colorTextSecondary }
                        HusInput {
                            Layout.fillWidth: true
                            text: vmWeaponEditor.decodedText
                            onEditingFinished: vmWeaponEditor.setDecodedText(text)
                        }
                    }
                }
            }

            // 操作行
            RowLayout {
                spacing: 8
                HusButton {
                    text: buttonsLoc.update_weapon || ""
                    enabled: vmWeaponEditor.hasSelection
                    onClicked: vmWeaponEditor.updateWeapon()
                }
                HusIconButton {
                    text: buttonsLoc.add_to_backpack || ""
                    type: HusButton.Type_Primary
                    iconSource: HusIcon.PlusOutlined
                    enabled: vmWeaponEditor.hasDecoded && appBridge.saveLoaded
                    onClicked: vmWeaponEditor.addNewWeaponToBackpack()
                }
                AppSelect {
                    Layout.preferredWidth: 150
                    model: vmWeaponEditor.flagOptions
                    currentIndex: vmWeaponEditor.flagIndex
                    onActivated: function(index) { vmWeaponEditor.setFlagIndex(index); }
                }
                Item { Layout.fillWidth: true }
            }

            // 头部信息 + 属性
            GlassPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: headerColumn.implicitHeight + 28

                ColumnLayout {
                    id: headerColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    spacing: 8
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 5
                        columnSpacing: 10
                        rowSpacing: 4
                        HusText { horizontalAlignment: Text.AlignHCenter; text: labelsLoc.manufacturer || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        HusText { horizontalAlignment: Text.AlignHCenter; text: labelsLoc.weapon_type || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        HusText { horizontalAlignment: Text.AlignHCenter; text: labelsLoc.rarity || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        HusText { horizontalAlignment: Text.AlignHCenter; text: labelsLoc.level || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        HusText { horizontalAlignment: Text.AlignHCenter; text: labelsLoc.seed || ""; color: HusTheme.Primary.colorTextSecondary; font.pixelSize: 11 }
                        HusInput {
                            Layout.fillWidth: true
                            readOnly: true
                            text: vmWeaponEditor.manufacturerText
                            horizontalAlignment: Text.AlignHCenter
                        }
                        HusInput {
                            Layout.fillWidth: true
                            readOnly: true
                            text: vmWeaponEditor.weaponTypeText
                            horizontalAlignment: Text.AlignHCenter
                        }
                        AppSelect {
                            Layout.fillWidth: true
                            model: vmWeaponEditor.rarityEditable ? vmWeaponEditor.rarityOptions : [vmWeaponEditor.rarityText]
                            currentIndex: vmWeaponEditor.rarityEditable ? vmWeaponEditor.rarityIndex : 0
                            enabled: vmWeaponEditor.rarityEditable
                            onActivated: function(index) { vmWeaponEditor.setRarityIndex(index); }
                        }
                        HusInput {
                            Layout.fillWidth: true
                            text: vmWeaponEditor.levelText
                            horizontalAlignment: Text.AlignHCenter
                            validator: IntValidator { bottom: 1; top: 100 }
                            onEditingFinished: vmWeaponEditor.setLevelText(text)
                        }
                        RowLayout {
                            spacing: 4
                            HusInput {
                                Layout.fillWidth: true
                                text: vmWeaponEditor.seedText
                                horizontalAlignment: Text.AlignHCenter
                                validator: IntValidator { }
                                onEditingFinished: vmWeaponEditor.setSeedText(text)
                            }
                            HusIconButton {
                                iconSource: HusIcon.ReloadOutlined
                                contentDescription: "🎲"
                                onClicked: vmWeaponEditor.randomizeSeed()
                            }
                        }
                    }
                    HusText {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        text: vmWeaponEditor.weaponNameText
                        font.bold: true
                        color: HusTheme.Primary.colorTextBase
                        elide: Text.ElideRight
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 4
                        columnSpacing: 10
                        rowSpacing: 6
                        Repeater {
                            model: vmWeaponEditor.statsPreview
                            delegate: Column {
                                Layout.fillWidth: true
                                spacing: 1
                                HusText {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: modelData.label
                                    color: HusTheme.Primary.colorTextSecondary
                                    font.pixelSize: 11
                                }
                                HusText {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: modelData.value
                                    color: HusTheme.Primary.colorTextBase
                                    font.bold: true
                                }
                            }
                        }
                    }
                }
            }

            // 部件
            GlassPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: partsColumn.implicitHeight + 28

                ColumnLayout {
                    id: partsColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    spacing: 8
                    RowLayout {
                        spacing: 8
                        HusText {
                            text: labelsLoc.weapon_parts || ""
                            font.bold: true
                            color: HusTheme.Primary.colorTextBase
                        }
                        HusTag {
                            text: vmWeaponEditor.legalityBadge.text
                            presetColor: vmWeaponEditor.legalityBadge.status === "legal" ? "green"
                                       : vmWeaponEditor.legalityBadge.status === "unknown" ? "default" : "orange"
                        }
                        Item { Layout.fillWidth: true }
                        HusIconButton {
                            iconSource: HusIcon.ReloadOutlined
                            contentDescription: (loc.tooltips || ({})).refresh_parts || ""
                            onClicked: vmWeaponEditor.forceRefreshParts()
                        }
                        HusButton {
                            text: "</>"
                            checkable: true
                            checked: vmWeaponEditor.showInternalNames
                            contentDescription: (loc.tooltips || ({})).toggle_internal_names || ""
                            onClicked: vmWeaponEditor.setShowInternalNames(checked)
                        }
                        HusButton {
                            text: buttonsLoc.add_part || ""
                            enabled: vmWeaponEditor.hasDecoded
                            onClicked: {
                                var catalog = vmWeaponEditor.prepareAddPartCatalog();
                                if (catalog.items && catalog.items.length > 0) {
                                    addPartDialog.catalog = catalog;
                                    addPartDialog.open();
                                }
                            }
                        }
                        HusButton {
                            text: buttonsLoc.add_skin || ""
                            enabled: vmWeaponEditor.hasDecoded
                            onClicked: {
                                if (vmWeaponEditor.prepareSkinOptions() > 0)
                                    skinDialog.open();
                            }
                        }
                    }

                    EmptyHint {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 96
                        visible: vmWeaponEditor.partRows.length === 0
                        description: labelsLoc.parse_serial_to_show_parts || ""
                    }

                    Repeater {
                        model: vmWeaponEditor.partRows
                        delegate: Rectangle {
                            id: partRow
                            Layout.fillWidth: true
                            Layout.preferredHeight: partCol.implicitHeight + 12
                            radius: 6
                            property bool selected: page.selectedPartIndex === modelData.index
                            color: selected ? selStyle.bg : (HusTheme.isDark ? "#1AFFFFFF" : "#0D000000")

                            // 行选择（置于内容下层，不挡按钮）；Ctrl+C 由 editFlick 处理
                            MouseArea {
                                anchors.fill: parent
                                z: -1
                                onClicked: {
                                    page.selectedPartIndex = modelData.index;
                                    editFlick.forceActiveFocus();
                                }
                            }

                            ColumnLayout {
                                id: partCol
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 6
                                spacing: 3

                                // 简单部件头
                                RowLayout {
                                    visible: modelData.kind === "simple"
                                    spacing: 8
                                    HusText {
                                        text: "⋮⋮"
                                        color: partRow.selected ? selStyle.tertiaryText : HusTheme.Primary.colorTextTertiary
                                    }
                                    Rectangle {
                                        radius: 4
                                        color: "transparent"
                                        border.color: PartColors.visible(modelData.color, HusTheme.isDark)
                                        border.width: 1
                                        implicitWidth: typeTagText.implicitWidth + 12
                                        implicitHeight: typeTagText.implicitHeight + 6
                                        HusText {
                                            id: typeTagText
                                            anchors.centerIn: parent
                                            text: modelData.typeText
                                            color: PartColors.visible(modelData.color, HusTheme.isDark)
                                            font.pixelSize: 11
                                        }
                                    }
                                    HusText {
                                        Layout.fillWidth: true
                                        text: modelData.name + (modelData.internal ? "  " + modelData.internal : "")
                                        color: partRow.selected ? selStyle.text : HusTheme.Primary.colorTextBase
                                        wrapMode: Text.Wrap
                                    }
                                    HusText {
                                        text: modelData.idText
                                        color: partRow.selected ? selStyle.tertiaryText : HusTheme.Primary.colorTextTertiary
                                        font.pixelSize: 11
                                    }
                                    HusIconButton {
                                        visible: modelData.isSkin
                                        text: "✎"
                                        onClicked: skinDialog.openForPart(modelData.index)
                                    }
                                    HusIconButton {
                                        visible: !modelData.isSkin
                                        iconSource: HusIcon.UpOutlined
                                        contentDescription: "up"
                                        onClicked: vmWeaponEditor.movePart(modelData.index, -1)
                                    }
                                    HusIconButton {
                                        visible: !modelData.isSkin
                                        iconSource: HusIcon.DownOutlined
                                        contentDescription: "down"
                                        onClicked: vmWeaponEditor.movePart(modelData.index, 1)
                                    }
                                    HusIconButton {
                                        iconSource: HusIcon.CloseOutlined
                                        contentDescription: "remove"
                                        onClicked: vmWeaponEditor.deletePart(modelData.index)
                                    }
                                }

                                // 组头
                                RowLayout {
                                    visible: modelData.kind === "group"
                                    spacing: 8
                                    HusText { text: "⋮⋮"; color: partRow.selected ? selStyle.tertiaryText : HusTheme.Primary.colorTextTertiary }
                                    HusButton {
                                        text: modelData.expanded ? "▾" : "▸"
                                        onClicked: vmWeaponEditor.toggleGroup(modelData.index)
                                    }
                                    HusText {
                                        Layout.fillWidth: true
                                        // simple 行无 title 字段，隐藏行也会求值绑定，须兜底
                                        text: modelData.title ?? ""
                                        color: partRow.selected ? selStyle.text : HusTheme.Primary.colorTextBase
                                        font.bold: true
                                        wrapMode: Text.Wrap
                                    }
                                    HusIconButton {
                                        iconSource: HusIcon.CloseOutlined
                                        contentDescription: "remove"
                                        onClicked: vmWeaponEditor.deletePart(modelData.index)
                                    }
                                }

                                // 描述（简单部件）
                                HusText {
                                    visible: modelData.kind === "simple" && modelData.stat !== ""
                                    text: modelData.stat
                                    color: partRow.selected ? selStyle.secondaryText : HusTheme.Primary.colorTextSecondary
                                    font.pixelSize: 11
                                    wrapMode: Text.Wrap
                                    Layout.fillWidth: true
                                }

                                // 组内容
                                Repeater {
                                    model: modelData.kind === "group" && modelData.expanded ? modelData.subs : []
                                    delegate: Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: subCol.implicitHeight + 8
                                        radius: 4
                                        color: HusTheme.isDark ? "#14FFFFFF" : "#08000000"
                                        ColumnLayout {
                                            id: subCol
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.top: parent.top
                                            anchors.margins: 4
                                            spacing: 2
                                            RowLayout {
                                                spacing: 8
                                                HusText { text: modelData.idText; color: HusTheme.Primary.colorTextTertiary; font.pixelSize: 11 }
                                                HusText {
                                                    Layout.fillWidth: true
                                                    text: modelData.name + (modelData.internal ? "  " + modelData.internal : "")
                                                     color: PartColors.visible(modelData.color, HusTheme.isDark)
                                                    wrapMode: Text.Wrap
                                                }
                                            }
                                            HusText {
                                                visible: modelData.stat !== ""
                                                text: modelData.stat
                                                color: HusTheme.Primary.colorTextSecondary
                                                font.pixelSize: 11
                                                wrapMode: Text.Wrap
                                                Layout.fillWidth: true
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: 6 }
        }
    }

    // ---- 添加配件对话框（对齐主线 FacetedCatalogPicker 三栏：筛选侧栏 + 可用列表
    //      + 预览卡片/已选清单；样式与幸运 Roll 约束弹层一致的卡片化风格） ----
    HusModal {
        id: addPartDialog
        objectName: "addPartDialog"
        width: 1180
        height: 720
        closable: true
        title: (loc.dialogs || ({})).add_part_title || ""
        // 弹窗底色：与 rollDialog 一致的清爽深/浅色（套件默认暗浊色观感差）
        colorBg: HusTheme.isDark ? "#1f242d" : "#f7f8fa"

        property var catalog: null
        property string searchText: ""
        property string facetType: "all"
        property string facetMfg: "all"
        property string facetWeapon: "all"
        // 已暂存条目：[{key,label,count}]（重复 stage 累加计数）
        property var staged: []
        // 当前预览项（null=无）
        property var previewItem: null
        // 各 facet 的当前行（-1=全部）
        property int facetTypeRow: 0
        property int facetMfgRow: 0
        property int facetWeaponRow: 0

        function filtered() {
            if (!catalog) return [];
            var result = [];
            var q = searchText.toLowerCase();
            for (var i = 0; i < catalog.items.length; i++) {
                var item = catalog.items[i];
                if (facetType !== "all" && item.category !== facetType) continue;
                if (facetMfg !== "all" && item.subcategory !== facetMfg) continue;
                if (facetWeapon !== "all" && item.tertiary !== facetWeapon) continue;
                if (q !== "" && (item.searchText || item.label).toLowerCase().indexOf(q) < 0) continue;
                result.push(item);
            }
            return result;
        }

        function resultText() {
            var n = catalog ? filtered().length : 0;
            var total = catalog ? catalog.items.length : 0;
            return ((page.loc.catalog || ({})).result_count || "{n} / {total}")
                .replace("{n}", n).replace("{total}", total);
        }

        function stage(item) {
            var next = staged.slice();
            for (var j = 0; j < next.length; j++)
                if (next[j].key === item.key) {
                    next[j] = { key: next[j].key, label: next[j].label, count: next[j].count + 1 };
                    _commitStaged(next);
                    return;
                }
            next.push({ key: item.key, label: item.title || item.label, count: 1 });
            _commitStaged(next);
        }

        function stageByKey(key) {
            if (!catalog) return;
            for (var i = 0; i < catalog.items.length; i++)
                if (catalog.items[i].key === key) { stage(catalog.items[i]); return; }
        }

        function removeStaged(index) {
            var next = staged.slice();
            next.splice(index, 1);
            _commitStaged(next);
        }

        function setStagedCount(index, value) {
            if (index >= 0 && index < staged.length) {
                var next = staged.slice();
                next[index] = { key: next[index].key, label: next[index].label,
                                count: Math.max(1, Math.min(20, Math.round(value))) };
                _commitStaged(next);
            }
        }

        // 原地修改数组不触发属性变更信号；统一走"拷贝替换"让绑定自然刷新
        function _commitStaged(next) { staged = next; }

        onVisibleChanged: if (visible) {
            searchText = "";
            facetType = "all"; facetMfg = "all"; facetWeapon = "all";
            facetTypeRow = 0; facetMfgRow = 0; facetWeaponRow = 0;
            previewItem = null;
        }

        contentDelegate: Item {
            implicitHeight: addPartDialog.height - 4

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 10

                // 标题行
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    HusText {
                        Layout.fillWidth: true
                        text: (page.loc.dialogs || ({})).select_parts_to_add || ""
                        font.bold: true
                        font.pixelSize: 15
                        color: HusTheme.Primary.colorTextBase
                        elide: Text.ElideRight
                    }
                    HusText {
                        text: addPartDialog.resultText()
                        color: HusTheme.Primary.colorTextSecondary
                        font.pixelSize: 12
                    }
                }

                // 顶部搜索（全宽）
                HusInput {
                    Layout.fillWidth: true
                    placeholderText: (page.loc.catalog || ({})).search_part || "🔍"
                    onTextChanged: addPartDialog.searchText = text
                }

                // 三栏主体
                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 10

                    // 左：筛选侧栏（三个单选列表，超出可见行数后各自滚动）
                    Rectangle {
                        Layout.preferredWidth: 230
                        Layout.maximumWidth: 230
                        Layout.fillHeight: true
                        color: selStyle.cardBg
                        border.color: selStyle.cardBorder
                        border.width: 1
                        radius: 10
                        clip: true

                        // 侧栏内容可滚动（三组列表总高超出面板时兜底）
                        LockedFlickable {
                            anchors.fill: parent
                            contentWidth: width
                            contentHeight: sidebarColumn.implicitHeight
                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: HusScrollBar { }

                            ColumnLayout {
                                id: sidebarColumn
                                width: parent.width
                                spacing: 10

                            Repeater {
                                model: [
                                    { title: (page.loc.catalog || ({})).facet_part_type || qsTr("Part Type"),
                                      list: addPartDialog.catalog ? addPartDialog.catalog.partTypes : [],
                                      row: "facetTypeRow", facet: "facetType" },
                                    { title: (page.loc.catalog || ({})).facet_manufacturer || qsTr("Manufacturer"),
                                      list: addPartDialog.catalog ? addPartDialog.catalog.manufacturers : [],
                                      row: "facetMfgRow", facet: "facetMfg" },
                                    { title: (page.loc.catalog || ({})).facet_weapon_type || qsTr("Weapon Type"),
                                      list: addPartDialog.catalog ? addPartDialog.catalog.weaponTypes : [],
                                      row: "facetWeaponRow", facet: "facetWeapon" },
                                ]
                                delegate: ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 4
                                    required property var modelData
                                    readonly property var facetSpec: modelData
                                    HusText {
                                        text: modelData.title
                                        font.bold: true
                                        font.pixelSize: 12
                                        color: HusTheme.Primary.colorTextSecondary
                                    }
                                    LockedListView {
                                        id: facetList
                                        Layout.fillWidth: true
                                        // 最多可见 6 行（主线 FacetGroup max_visible 默认值；
                                        // 三组合计高度须容纳于侧栏，超出部分列表内滚动）
                                        Layout.preferredHeight: Math.min(modelData.list.length, 6) * 26 + 2
                                        clip: true
                                        boundsBehavior: Flickable.StopAtBounds
                                        model: modelData.list
                                        currentIndex: modelData.row === "facetTypeRow" ? addPartDialog.facetTypeRow
                                                   : modelData.row === "facetMfgRow" ? addPartDialog.facetMfgRow
                                                   : addPartDialog.facetWeaponRow
                                        onCurrentIndexChanged: {
                                            if (count > 0 && currentIndex >= 0 && modelData.list.length > 0) {
                                                var opt = modelData.list[currentIndex];
                                                if (modelData.facet === "facetType") addPartDialog.facetType = opt.key;
                                                else if (modelData.facet === "facetMfg") addPartDialog.facetMfg = opt.key;
                                                else addPartDialog.facetWeapon = opt.key;
                                                if (modelData.facet === "facetType") addPartDialog.facetTypeRow = currentIndex;
                                                else if (modelData.facet === "facetMfg") addPartDialog.facetMfgRow = currentIndex;
                                                else addPartDialog.facetWeaponRow = currentIndex;
                                            }
                                        }
                                        delegate: Item {
                                            width: ListView.view.width
                                            height: 26
                                            readonly property bool facetSelected:
                                                modelData.key === (facetSpec.facet === "facetType" ? addPartDialog.facetType
                                                                 : facetSpec.facet === "facetMfg" ? addPartDialog.facetMfg
                                                                 : addPartDialog.facetWeapon)
                                            Rectangle {
                                                anchors.fill: parent
                                                radius: 4
                                                color: facetSelected ? selStyle.bgSubtle
                                                     : facetItemHover.containsMouse ? selStyle.hover
                                                     : "transparent"
                                            }
                                            HusText {
                                                anchors.fill: parent
                                                anchors.leftMargin: 8
                                                verticalAlignment: Text.AlignVCenter
                                                text: modelData.label
                                                color: facetSelected ? HusTheme.Primary.colorTextBase
                                                     : HusTheme.Primary.colorTextSecondary
                                                font.pixelSize: 12
                                                elide: Text.ElideRight
                                            }
                                            MouseArea {
                                                id: facetItemHover
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                onClicked: facetList.currentIndex = index
                                            }
                                        }
                                    }
                                }
                            }
                            }
                        }
                    }

                    // 中：可用列表（双击/单击加号暂存）
                    // 注意：fillWidth + implicitWidth 0 的 Rectangle 在 RowLayout 中会被
                    // 首选宽度的兄弟列挤压成 0（Qt 布局的经典陷阱），须给 preferredWidth
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 400
                        Layout.minimumWidth: 200
                        Layout.fillHeight: true
                        color: selStyle.cardBg
                        border.color: selStyle.cardBorder
                        border.width: 1
                        radius: 10
                        clip: true

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 6

                            HusText {
                                text: (page.loc.catalog || ({})).available_parts_hint
                                      || (page.loc.catalog || ({})).available_parts || ""
                                font.bold: true
                                font.pixelSize: 12
                                color: HusTheme.Primary.colorTextSecondary
                            }

                            LockedListView {
                                id: availList
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                ScrollBar.vertical: HusScrollBar { }
                                model: addPartDialog.filtered()
                                onContentYChanged: HoverTip.hide()
                                // 行悬停：完整说明（候选 hint + 模型 + 描述 + 内部名）

                                delegate: Item {
                                    width: ListView.view.width
                                    height: 40
                                    Rectangle {
                                        anchors.fill: parent
                                        anchors.margins: 1
                                        radius: 5
                                        // legit 候选上色 + 同/跨模型着色（对齐主线 _refilter）
                                        color: modelData.candidateKind === "legal" ? selStyle.legitBg
                                             : modelData.candidateKind === "warning" ? selStyle.warningBg
                                             : addHover.containsMouse ? selStyle.hover
                                             : "transparent"
                                    }
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 8
                                        anchors.rightMargin: 4
                                        spacing: 6
                                        HusText {
                                            Layout.fillWidth: true
                                            text: (modelData.candidateMarker ? modelData.candidateMarker + "  " : "")
                                                  + modelData.label
                                            color: modelData.modelKind === "same" ? "#39aee8"
                                                 : modelData.modelKind === "cross" ? "#d99a3e"
                                                 : HusTheme.Primary.colorTextBase
                                            font.bold: modelData.candidateKind === "legal"
                                            font.pixelSize: 12
                                            elide: Text.ElideRight
                                        }
                                        // 暂存按钮（对齐主线"单击预览，双击添加"补充快速通道）
                                        HusIconButton {
                                            iconSource: HusIcon.PlusOutlined
                                            contentDescription: "add"
                                            Layout.alignment: Qt.AlignVCenter
                                            Layout.preferredWidth: 30
                                            Layout.preferredHeight: 30
                                            iconSize: 16
                                            onClicked: addPartDialog.stage(modelData)
                                        }
                                    }
                                    MouseArea {
                                        id: addHover
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        onClicked: addPartDialog.previewItem = modelData
                                        onDoubleClicked: addPartDialog.stage(modelData)
                                        onEntered: HoverTip.showFor(addHover, modelData.tooltip || "", mouseX, mouseY)
                                        onPositionChanged: HoverTip.showFor(addHover, modelData.tooltip || "", mouseX, mouseY)
                                        onExited: HoverTip.hideFor(addHover)
                                    }


                                }
                                EmptyHint {
                                    anchors.fill: parent
                                    visible: addPartDialog.filtered().length === 0
                                    description: (page.loc.catalog || ({})).no_matches || "—"
                                }
                            }
                        }
                    }

                    // 右：预览卡片 + 已选清单（固定宽，防止被中栏挤压/膨胀）
                    ColumnLayout {
                        Layout.preferredWidth: 300
                        Layout.maximumWidth: 300
                        Layout.fillHeight: true
                        spacing: 10

                        // 预览卡片（对齐主线 previewCard：标题 + 徽标 + 详情）
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.preferredHeight: 180
                            color: selStyle.cardBg
                            border.color: selStyle.cardBorder
                            border.width: 1
                            radius: 10
                            clip: true

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 6
                                HusText {
                                    Layout.fillWidth: true
                                    text: addPartDialog.previewItem
                                          ? (addPartDialog.previewItem.title || addPartDialog.previewItem.label) : "—"
                                    font.bold: true
                                    font.pixelSize: 13
                                    color: HusTheme.Primary.colorTextBase
                                    wrapMode: Text.Wrap
                                }
                                // 徽标行（同/跨模型 + 候选 badge + 分类）
                                Flow {
                                    Layout.fillWidth: true
                                    spacing: 4
                                    visible: addPartDialog.previewItem !== null
                                    Repeater {
                                        model: {
                                            var it = addPartDialog.previewItem;
                                            if (!it) return [];
                                            var badges = (it.badges || []).slice();
                                            if (it.candidateBadge) badges.unshift(it.candidateBadge);
                                            return badges;
                                        }
                                        delegate: Rectangle {
                                            radius: 4
                                            color: HusTheme.isDark ? "#26FFFFFF" : "#14000000"
                                            implicitWidth: badgeText.implicitWidth + 10
                                            implicitHeight: badgeText.implicitHeight + 4
                                            HusText {
                                                id: badgeText
                                                anchors.centerIn: parent
                                                text: modelData
                                                font.pixelSize: 10
                                                color: HusTheme.Primary.colorTextSecondary
                                            }
                                        }
                                    }
                                }
                                LockedFlickable {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    contentWidth: width
                                    contentHeight: previewText.implicitHeight
                                    clip: true
                                    boundsBehavior: Flickable.StopAtBounds
                                    ScrollBar.vertical: HusScrollBar { }
                                    Text {
                                        id: previewText
                                        width: parent.width
                                        text: addPartDialog.previewItem
                                              ? (addPartDialog.previewItem.detail || "") : ""
                                        textFormat: Text.PlainText
                                        wrapMode: Text.Wrap
                                        color: HusTheme.Primary.colorTextSecondary
                                        font.pixelSize: 11
                                    }
                                }
                            }
                        }

                        // 已选清单（对齐主线 sel_card：计数 + 行 + 清空）
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.preferredHeight: 220
                            color: selStyle.cardBg
                            border.color: selStyle.cardBorder
                            border.width: 1
                            radius: 10
                            clip: true

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 6
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    HusText {
                                        Layout.fillWidth: true
                                        text: ((page.loc.catalog || ({})).selected_parts || "Selected")
                                              + "  (" + addPartDialog.staged.length + ")"
                                        font.bold: true
                                        font.pixelSize: 12
                                        color: HusTheme.Primary.colorPrimary
                                        elide: Text.ElideRight
                                    }
                                    HusButton {
                                        text: (page.loc.catalog || ({})).clear || "Clear"
                                        visible: addPartDialog.staged.length > 0
                                        onClicked: addPartDialog._commitStaged([])
                                    }
                                }
                                LockedListView {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    boundsBehavior: Flickable.StopAtBounds
                                    ScrollBar.vertical: HusScrollBar { }
                                    model: addPartDialog.staged
                                    delegate: RowLayout {
                                        width: ListView.view.width
                                        height: 36
                                        spacing: 6
                                        HusText {
                                            Layout.fillWidth: true
                                            text: modelData.label
                                            color: HusTheme.Primary.colorTextBase
                                            font.pixelSize: 11
                                            elide: Text.ElideRight
                                        }
                                        CountStepper {
                                            min: 1
                                            max: 20
                                            value: modelData.count
                                            Layout.alignment: Qt.AlignVCenter
                                            onStepped: function(delta) {
                                                addPartDialog.setStagedCount(index, modelData.count + delta);
                                            }
                                            onValueCommitted: function(v) {
                                                addPartDialog.setStagedCount(index, v);
                                            }
                                        }
                                        HusIconButton {
                                            iconSource: HusIcon.CloseOutlined
                                            contentDescription: "remove"
                                            Layout.preferredWidth: 24
                                            Layout.preferredHeight: 24
                                            onClicked: addPartDialog.removeStaged(index)
                                        }
                                    }
                                    EmptyHint {
                                        anchors.fill: parent
                                        visible: addPartDialog.staged.length === 0
                                        description: (page.loc.dialogs || ({})).no_selection || ""
                                    }
                                }
                            }
                        }
                    }
                }

                // 底部操作行
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Item { Layout.fillWidth: true }
                    HusButton {
                        text: buttonsLoc.confirm_add || ""
                        type: HusButton.Type_Primary
                        enabled: addPartDialog.staged.length > 0
                        onClicked: {
                            vmWeaponEditor.addParts(addPartDialog.staged.map(function(e) {
                                return { key: e.key, count: e.count };
                            }));
                            addPartDialog._commitStaged([]);
                            addPartDialog.close();
                        }
                    }
                }
            }
        }
    }

    // ---- 皮肤选择对话框（铺满高度 + 卡片化，样式与添加配件对话框一致） ----
    HusModal {
        id: skinDialog
        objectName: "skinDialog"
        width: 520
        height: 620
        closable: true
        title: (loc.dialogs || ({})).select_skin_title || ""
        colorBg: HusTheme.isDark ? "#1f242d" : "#f7f8fa"

        property int partIndex: -1
        property string searchText: ""

        function openForPart(index) {
            partIndex = index;
            searchText = "";
            open();
        }

        contentDelegate: Item {
            implicitHeight: skinDialog.height - 4

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 10

                // 自绘标题行（HusModal 的 title 委托被自定义 contentDelegate 覆盖）
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    HusText {
                        Layout.fillWidth: true
                        text: (loc.dialogs || ({})).select_skin_title || ""
                        font.bold: true
                        font.pixelSize: 15
                        color: HusTheme.Primary.colorTextBase
                        elide: Text.ElideRight
                    }
                }

                HusText {
                    Layout.fillWidth: true
                    text: (loc.dialogs || ({})).select_skin_msg || ""
                    color: HusTheme.Primary.colorTextSecondary
                    wrapMode: Text.Wrap
                    font.pixelSize: 12
                }

                HusInput {
                    Layout.fillWidth: true
                    placeholderText: (loc.catalog || ({})).search_skin || qsTr("搜索皮肤…")
                    onTextChanged: skinDialog.searchText = text
                }

                // 皮肤列表（卡片 + 填满剩余高度，消除底部死区）
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: selStyle.cardBg
                    border.color: selStyle.cardBorder
                    border.width: 1
                    radius: 10
                    clip: true

                    LockedListView {
                        id: skinList
                        anchors.fill: parent
                        anchors.margins: 8
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: HusScrollBar { }
                        model: {
                            var q = skinDialog.searchText.toLowerCase();
                            var all = vmWeaponEditor.skinOptions;
                            if (q === "") return all;
                            return all.filter(function(o) { return o.label.toLowerCase().indexOf(q) >= 0; });
                        }
                        delegate: Item {
                            width: skinList.width
                            height: 34
                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: 1
                                radius: 5
                                color: skinHover.containsMouse ? selStyle.hover : "transparent"
                            }
                            HusText {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                verticalAlignment: Text.AlignVCenter
                                text: modelData.label
                                color: HusTheme.Primary.colorTextBase
                                font.pixelSize: 12
                                elide: Text.ElideRight
                            }
                            MouseArea {
                                id: skinHover
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: {
                                    vmWeaponEditor.applySkin(skinDialog.partIndex, modelData.id);
                                    skinDialog.close();
                                    skinDialog.partIndex = -1;
                                }
                            }
                        }
                        EmptyHint {
                            anchors.fill: parent
                            visible: skinList.count === 0
                            description: (page.loc.dialogs || ({})).no_selection || ""
                        }
                    }
                }
            }
        }
    }
}
