import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "../components"
import "../components/CopyKeys.js" as CopyKeys

// 序列号检视页：对齐主线 QtSerialInspectorTab（只读，绝不写存档）
ColumnLayout {
    id: page
    anchors.fill: parent
    anchors.margins: 0
    spacing: 10

    readonly property var loc: vmSerialInspector.strings

    // 部件卡片选中项（Ctrl+C 复制目标，-1 表示无）
    property int selectedPartIndex: -1

    SelectionStyle { id: selStyle }

    Component.onCompleted: vmSerialInspector.refresh()

    Connections {
        target: vmSerialInspector
        function onInputRequested(text) { inputArea.text = text; }
    }

    HusImagePreview { id: cardPreview }

    SerialCatalogDialog {
        id: catalogDialog
        loc: page.loc.catalog || {}
    }

    HusText {
        text: page.loc.labels ? page.loc.labels.input : "Serial (Base85 or decoded)"
        font.bold: true
        color: HusTheme.Primary.colorTextBase
    }

    HusTextArea {
        id: inputArea
        Layout.fillWidth: true
        Layout.preferredHeight: 70
        placeholderText: page.loc.labels ? page.loc.labels.empty : ""
        onTextChanged: vmSerialInspector.setInput(text)
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 6
        HusText {
            text: page.loc.labels ? page.loc.labels.base85 : "Base85"
            color: HusTheme.Primary.colorTextSecondary
            Layout.preferredWidth: 90
        }
        HusInput {
            id: base85Field
            Layout.fillWidth: true
            readOnly: true
            text: vmSerialInspector.base85
            onTextChanged: if (!activeFocus) cursorPosition = 0
        }
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.copy : "Copy"
            iconSource: HusIcon.CopyOutlined
            enabled: !!vmSerialInspector.base85
            onClicked: vmSerialInspector.copyForm("base85")
        }
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.use : "Edit this form"
            iconSource: HusIcon.EditOutlined
            enabled: !!vmSerialInspector.base85
            onClicked: vmSerialInspector.useForm("base85")
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 6
        HusText {
            text: page.loc.labels ? page.loc.labels.decoded : "Decoded"
            color: HusTheme.Primary.colorTextSecondary
            Layout.preferredWidth: 90
        }
        HusInput {
            id: decodedField
            Layout.fillWidth: true
            readOnly: true
            text: vmSerialInspector.decoded
            onTextChanged: if (!activeFocus) cursorPosition = 0
        }
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.copy : "Copy"
            iconSource: HusIcon.CopyOutlined
            enabled: !!vmSerialInspector.decoded
            onClicked: vmSerialInspector.copyForm("decoded")
        }
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.use : "Edit this form"
            iconSource: HusIcon.EditOutlined
            enabled: !!vmSerialInspector.decoded
            onClicked: vmSerialInspector.useForm("decoded")
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.catalog : "Internal / NPC / Mission presets"
            iconSource: HusIcon.ProfileOutlined
            onClicked: { if (vmSerialInspector.openCatalog()) catalogDialog.open(); }
        }
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.inspect : "Inspect"
            iconSource: HusIcon.SearchOutlined
            type: HusButton.Type_Primary
            onClicked: vmSerialInspector.inspect()
        }
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.paste : "Paste"
            iconSource: HusIcon.SnippetsOutlined
            onClicked: vmSerialInspector.paste()
        }
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.clear : "Clear"
            iconSource: HusIcon.ClearOutlined
            onClicked: vmSerialInspector.clear()
        }
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.copy_json : "Copy JSON"
            iconSource: HusIcon.CodeOutlined
            enabled: vmSerialInspector.hasReport
            onClicked: vmSerialInspector.copyJson()
        }
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.export_json : "Export JSON"
            iconSource: HusIcon.ExportOutlined
            enabled: vmSerialInspector.hasReport
            onClicked: vmSerialInspector.exportJson()
        }
        HusIconButton {
            text: page.loc.buttons ? page.loc.buttons.save_card : "Save card image"
            iconSource: HusIcon.FileImageOutlined
            enabled: vmSerialInspector.hasCard
            onClicked: vmSerialInspector.saveCard()
        }
        Item { Layout.fillWidth: true }
        HusTag {
            visible: !!vmSerialInspector.statusText
            text: vmSerialInspector.statusText
            presetColor: vmSerialInspector.statusColor || "#B0BEC5"
        }
    }

    GlassPanel {
        Layout.fillWidth: true
        implicitHeight: summaryColumn.implicitHeight + 20

        ColumnLayout {
            id: summaryColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 10
            spacing: 4

            HusText {
                visible: vmSerialInspector.summaryFirst.length === 0
                text: vmSerialInspector.summaryPlaceholder
                color: HusTheme.Primary.colorTextSecondary
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }

            Flow {
                visible: vmSerialInspector.summaryFirst.length > 0
                Layout.fillWidth: true
                spacing: 4
                Repeater {
                    model: vmSerialInspector.summaryFirst
                    delegate: Row {
                        spacing: 3
                        HusText { text: (modelData.label || "") + ":"; color: HusTheme.Primary.colorTextSecondary }
                        HusText { text: modelData.value || ""; color: HusTheme.Primary.colorTextBase }
                        Item { width: 12; height: 1 }
                    }
                }
            }

            Flow {
                visible: vmSerialInspector.summarySecond.length > 0
                Layout.fillWidth: true
                spacing: 4
                Repeater {
                    model: vmSerialInspector.summarySecond
                    delegate: Row {
                        spacing: 3
                        HusText { text: (modelData.label || "") + ":"; color: HusTheme.Primary.colorTextSecondary }
                        HusText { text: modelData.value || ""; color: HusTheme.Primary.colorTextBase }
                        Item { width: 12; height: 1 }
                    }
                }
            }

            ColumnLayout {
                visible: vmSerialInspector.hasProvenance
                Layout.fillWidth: true
                spacing: 2
                RowLayout {
                    spacing: 6
                    HusText {
                        text: page.loc.labels ? page.loc.labels.provenance : "Source"
                        color: HusTheme.Primary.colorTextSecondary
                    }
                    Repeater {
                        model: vmSerialInspector.provenanceTags
                        delegate: HusText {
                            text: modelData.text || ""
                            color: modelData.color || HusTheme.Primary.colorTextBase
                            font.bold: true
                        }
                    }
                }
                Repeater {
                    model: vmSerialInspector.provenanceContexts
                    delegate: HusText {
                        text: modelData || ""
                        color: HusTheme.Primary.colorTextSecondary
                        font.pixelSize: 11
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        spacing: 10

        HusTabView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            initModel: [
                { title: (page.loc.labels && page.loc.labels.parts) || "Parts", contentDelegate: partsContent },
                { title: (page.loc.labels && page.loc.labels.rules) || "Generation rules", contentDelegate: rulesContent }
            ]
        }

        GlassPanel {
            Layout.preferredWidth: 340
            Layout.fillHeight: true

            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 10
                spacing: 6

                HusText {
                    text: page.loc.labels ? page.loc.labels.card : "Item card"
                    font.bold: true
                    color: HusTheme.Primary.colorTextBase
                }
                HusText {
                    visible: !vmSerialInspector.hasCard && !!vmSerialInspector.cardMessage
                    text: vmSerialInspector.cardMessage
                    color: HusTheme.Primary.colorTextSecondary
                    wrapMode: Text.WordWrap
                    width: parent.width
                }
                Image {
                    visible: vmSerialInspector.hasCard
                    width: Math.min(300, parent.width)
                    fillMode: Image.PreserveAspectFit
                    source: vmSerialInspector.cardUrl
                    cache: false
                    smooth: true
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            cardPreview.clear();
                            cardPreview.append({ url: vmSerialInspector.cardUrl });
                            cardPreview.open();
                        }
                    }
                }
                HusText {
                    visible: vmSerialInspector.hasCard
                    text: page.loc.labels ? page.loc.labels.zoom_hint : ""
                    color: HusTheme.Primary.colorTextSecondary
                    font.pixelSize: 11
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
            }
        }
    }

    Component {
        id: partsContent
        Item {
            LockedFlickable {
                id: partsFlick
                anchors.fill: parent
                anchors.margins: 8
                contentWidth: width - 16
                contentHeight: partsColumn.implicitHeight + 8
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: HusScrollBar { }
                activeFocusOnTab: true

                // Ctrl+C 复制选中部件的标识（内部名）
                Keys.onPressed: function(event) {
                    if (CopyKeys.matchCopy(event))
                        vmSerialInspector.copyPart(page.selectedPartIndex);
                }

                Column {
                    id: partsColumn
                    width: parent.width
                    spacing: 6
                    Repeater {
                        model: vmSerialInspector.parts
                        delegate: SerialPartCard {
                            width: partsColumn.width
                            part: modelData
                            selected: page.selectedPartIndex === index
                            onClicked: {
                                page.selectedPartIndex = index;
                                partsFlick.forceActiveFocus();
                            }
                        }
                    }
                }

                // 空态只留一行提示文字（HusEmpty 会带一个套件插画图标，与页面风格不符）
                HusText {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: vmSerialInspector.parts.length === 0
                    text: page.loc.labels ? page.loc.labels.no_parts : "No parts to show."
                    color: HusTheme.Primary.colorTextTertiary
                }
            }
        }
    }

    Component {
        id: rulesContent
        Item {
            LockedFlickable {
                anchors.fill: parent
                anchors.margins: 8
                contentWidth: width - 16
                contentHeight: rulesText.implicitHeight + 8
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: HusScrollBar { }

                Text {
                    id: rulesText
                    width: parent.width
                    textFormat: Text.RichText
                    wrapMode: Text.WordWrap
                    color: HusTheme.Primary.colorTextBase
                    text: vmSerialInspector.rulesHtml
                }
            }
        }
    }
}
