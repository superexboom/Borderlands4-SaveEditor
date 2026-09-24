import QtQuick
import QtQuick.Layouts
import HuskarUI.Basic

ColumnLayout {
    id: section
    property string title: ""
    property var entries: []
    function richDetail(value) {
        var text = String(value || "");
        if (HusTheme.isDark) return text;
        return text.replace(/#d7dee8/ig, "#374151")
                   .replace(/#ffffff/ig, "#374151")
                   .replace(/#e8e8ec/ig, "#374151");
    }
    spacing: 5
    Layout.fillWidth: true
    HusText {
        text: section.title
        font.bold: true
        color: HusTheme.Primary.colorTextBase
    }
    Repeater {
        model: section.entries
        delegate: Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: entryRow.implicitHeight + 10
            radius: 6
            color: HusTheme.isDark ? "#22FFFFFF" : "#11000000"
            RowLayout {
                id: entryRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 6
                spacing: 8
                Item {
                    // Skill icons are optional. Missing art must collapse this
                    // slot instead of leaving a misleading empty frame.
                    visible: (modelData.icon || modelData.iconUrl || "") !== ""
                    Layout.preferredWidth: visible ? 34 : 0
                    Layout.preferredHeight: visible ? 34 : 0
                    Layout.alignment: Qt.AlignTop
                    Image {
                        anchors.fill: parent
                        source: modelData.icon || modelData.iconUrl || ""
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        asynchronous: true
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    HusText {
                        Layout.fillWidth: true
                        text: modelData.title || ""
                        color: modelData.accent || HusTheme.Primary.colorTextBase
                        font.bold: true
                        wrapMode: Text.Wrap
                    }
                    HusText {
                        Layout.fillWidth: true
                        visible: (modelData.description || "") !== ""
                        text: section.richDetail(modelData.description || "")
                        textFormat: Text.RichText
                        color: HusTheme.Primary.colorTextSecondary
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                    }
                }
                Rectangle {
                    // The rank belongs to the row metadata, not the icon slot.
                    visible: (modelData.level || "") !== ""
                    Layout.preferredWidth: 34
                    Layout.preferredHeight: 24
                    Layout.alignment: Qt.AlignTop
                    radius: 5
                    color: HusTheme.isDark ? "#334a90e2" : "#214a90e2"
                    HusText {
                        anchors.centerIn: parent
                        text: modelData.level || ""
                        color: "#ffffff"
                        font.bold: true
                        font.pixelSize: 11
                    }
                }
            }
        }
    }
}
