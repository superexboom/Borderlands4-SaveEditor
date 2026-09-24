import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import HuskarUI.Basic
import "../components"

// 转换器页：对齐主线 QtConverterTab 的四个分组（单条互转 / 批量互转 / 批量写入背包 / 迭代器）
LockedFlickable {
    id: scroll
    anchors.fill: parent
    anchors.margins: 0
    contentWidth: width
    contentHeight: layout.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: HusScrollBar { }

    readonly property var loc: vmConverter.strings

    Connections {
        target: vmConverter
        function onSerialResultReady(text) { serialInput.text = text }
        function onDeserResultReady(text) { deserInput.text = text }
    }

    ColumnLayout {
        id: layout
        width: scroll.width
        spacing: 12

        // ---- 分组一：单条互转 ----
        HusGroupBox {
            Layout.fillWidth: true
            title: scroll.loc.groups ? (scroll.loc.groups.single || "Single") : "Single"

            ColumnLayout {
                anchors.fill: parent
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    HusText {
                        text: scroll.loc.labels ? scroll.loc.labels.base85 : "Base85:"
                        color: HusTheme.Primary.colorTextBase
                        Layout.preferredWidth: 110
                    }
                    HusInput {
                        id: serialInput
                        Layout.fillWidth: true
                        placeholderText: scroll.loc.placeholders ? scroll.loc.placeholders.base85 : ""
                        onTextEdited: vmConverter.onSerialEdited(text)
                    }
                    HusIconButton {
                        iconSource: HusIcon.CopyOutlined
                        contentDescription: "copy"
                        onClicked: vmConverter.copySerial()
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    HusText {
                        text: scroll.loc.labels ? scroll.loc.labels.deserialize : "Deserialize:"
                        color: HusTheme.Primary.colorTextBase
                        Layout.preferredWidth: 110
                    }
                    HusInput {
                        id: deserInput
                        Layout.fillWidth: true
                        placeholderText: scroll.loc.placeholders ? scroll.loc.placeholders.deserialize : ""
                        onTextEdited: vmConverter.onDeserEdited(text)
                    }
                    HusIconButton {
                        iconSource: HusIcon.CopyOutlined
                        contentDescription: "copy"
                        onClicked: vmConverter.copyDeser()
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    HusText {
                        text: vmConverter.singleStatusText
                        color: vmConverter.singleStatusKind === "success" ? HusTheme.Primary.colorSuccess
                             : vmConverter.singleStatusKind === "error" ? HusTheme.Primary.colorError
                             : HusTheme.Primary.colorTextSecondary
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                    HusButton {
                        text: scroll.loc.buttons ? (scroll.loc.buttons.clear || "Clear") : "Clear"
                        onClicked: vmConverter.clearSingle()
                    }
                }
            }
        }

        // ---- 分组二：批量互转 ----
        HusGroupBox {
            Layout.fillWidth: true
            title: scroll.loc.groups ? (scroll.loc.groups.batch || "Batch") : "Batch"

            ColumnLayout {
                anchors.fill: parent
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    HusText {
                        text: scroll.loc.labels ? scroll.loc.labels.input_batch : "Input:"
                        color: HusTheme.Primary.colorTextBase
                        Layout.fillWidth: true
                    }
                    HusText {
                        text: scroll.loc.labels ? scroll.loc.labels.output : "Output:"
                        color: HusTheme.Primary.colorTextBase
                    }
                    HusButton {
                        text: scroll.loc.buttons ? (scroll.loc.buttons.export_txt || "Export .txt") : "Export .txt"
                        onClicked: vmConverter.exportBatch()
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    HusTextArea {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 170
                        onTextChanged: vmConverter.setBatchInput(text)
                    }
                    HusTextArea {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 170
                        readOnly: true
                        text: vmConverter.batchOutputText
                        colorText: HusTheme.Primary.colorTextBase
                    }
                }

                HusProgress {
                    Layout.fillWidth: true
                    percent: vmConverter.batchPercent
                    visible: vmConverter.batchRunning
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    HusButton {
                        text: vmConverter.batchRunning
                               ? (scroll.loc.buttons ? (scroll.loc.buttons.processing || "Processing...") : "Processing...")
                               : (scroll.loc.buttons ? (scroll.loc.buttons.start_batch || "Start Batch") : "Start Batch")
                        type: HusButton.Type_Primary
                        enabled: !vmConverter.batchRunning
                        onClicked: vmConverter.startBatch()
                    }
                    HusButton {
                        text: appBridge.trText("main_window.dialogs.cancel")
                        visible: vmConverter.batchRunning
                        onClicked: vmConverter.cancelBatch()
                    }
                    HusText {
                        text: vmConverter.batchStatusText
                        color: HusTheme.Primary.colorTextSecondary
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                }
            }
        }

        // ---- 分组三：批量写入背包 ----
        HusGroupBox {
            Layout.fillWidth: true
            title: scroll.loc.groups ? (scroll.loc.groups.batch_add || "Batch Add") : "Batch Add"

            ColumnLayout {
                anchors.fill: parent
                spacing: 8

                HusText {
                    text: scroll.loc.labels ? scroll.loc.labels.input_batch_add : "Input:"
                    color: HusTheme.Primary.colorTextBase
                }

                HusTextArea {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 130
                    enabled: !vmConverter.batchAddRunning && appBridge.saveLoaded
                    text: vmConverter.batchAddInput
                    onTextChanged: vmConverter.setBatchAddInput(text)
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    HusButton {
                        text: scroll.loc.buttons ? (scroll.loc.buttons.import_yaml || "导入 YAML") : "导入 YAML"
                        onClicked: vmConverter.importBatchAddYaml()
                    }
                    HusButton {
                        text: vmConverter.batchAddRunning
                               ? (scroll.loc.buttons ? (scroll.loc.buttons.adding || "Adding...") : "Adding...")
                               : (scroll.loc.buttons ? (scroll.loc.buttons.batch_add || "Batch Add") : "Batch Add")
                        type: HusButton.Type_Primary
                        enabled: appBridge.saveLoaded && !vmConverter.batchAddRunning
                        onClicked: vmConverter.startBatchAdd()
                    }
                    HusButton {
                        text: appBridge.trText("main_window.dialogs.cancel")
                        visible: vmConverter.batchAddRunning
                        onClicked: vmConverter.cancelBatchAdd()
                    }
                    Item { Layout.fillWidth: true }
                    HusText {
                        text: scroll.loc.labels ? scroll.loc.labels.select_flag : "Flag:"
                        color: HusTheme.Primary.colorTextBase
                    }
                    AppSelect {
                        Layout.preferredWidth: 190
                        model: vmConverter.flagOptions
                        currentIndex: vmConverter.batchAddFlagIndex
                        onActivated: function(index) { vmConverter.setBatchAddFlagIndex(index) }
                    }
                }

                HusProgress {
                    Layout.fillWidth: true
                    percent: vmConverter.batchAddPercent
                    visible: vmConverter.batchAddRunning
                }

                HusText {
                    text: vmConverter.batchAddStatusText
                    color: HusTheme.Primary.colorTextSecondary
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }

    }
}
