import QtQuick
import QtQuick.Layouts
import HuskarUI.Basic

Flow {
    id: legend
    // Read the language first so the binding re-evaluates on a language switch.
    function tr(path) {
        var language = appBridge.language;
        return appBridge.trText(path);
    }
    spacing: 12
    Repeater {
        model: [
            { label: legend.tr("candidate_legend.natural"), color: "#4a90e2" },
            { label: legend.tr("candidate_legend.blocked"), color: "#e6a439" },
            { label: legend.tr("candidate_legend.modified"), color: "#ce5b5b" },
            { label: legend.tr("candidate_legend.unknown"), color: "#687080" }
        ]
        delegate: Row {
            spacing: 5
            Rectangle {
                width: 9; height: 9; radius: 2
                anchors.verticalCenter: parent.verticalCenter
                color: modelData.color
            }
            HusText {
                text: modelData.label
                font.pixelSize: 11
                color: HusTheme.Primary.colorTextSecondary
            }
        }
    }
}
