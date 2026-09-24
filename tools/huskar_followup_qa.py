"""Deterministic QML integration checks; uses isolated settings and sample data."""
import os
import sys
import json
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','windows')
os.environ.setdefault('QSG_RHI_BACKEND','opengl')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ui_huskar.runtime import configure_runtime
runtime=configure_runtime()
from PyQt6.QtCore import QSettings,QUrl,QObject
from PyQt6.QtQml import QQmlApplicationEngine,QQmlComponent
from PyQt6.QtQuick import QQuickWindow,QSGRendererInterface
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from ui_huskar.__main__ import create_bridges

QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
app=QApplication([])
out=ROOT/'.local/followup-verified';out.mkdir(parents=True,exist_ok=True)
settings=QSettings(str(out/'isolated.ini'),QSettings.Format.IniFormat)
settings.setValue('autosave_enabled',False)
bridge,vms=create_bridges(settings)
bridge.controller.update_yaml_object((ROOT/'sth/1.yaml').read_text(encoding='utf8'))
bridge.controller.mark_clean()
engine=QQmlApplicationEngine();engine.addImportPath(str(runtime/'qml'))
warnings=[];engine.warnings.connect(lambda ws:warnings.extend(str(w.toString()) for w in ws))
engine.rootContext().setContextProperty('appBridge',bridge)
for key,vm in vms.items():engine.rootContext().setContextProperty('vm'+''.join(s.title() for s in key.split('_')),vm)
engine.load(QUrl.fromLocalFile(str(ROOT/'ui_huskar/qml/Main.qml')))
assert engine.rootObjects(),warnings
window=engine.rootObjects()[0]
window.resize(1200,800);window.show();QTest.qWait(200)
main_menu=window.findChild(QObject,'mainMenu');assert main_menu is not None
component=QQmlComponent(engine)
component.setData(('''import QtQuick
import "'''+(ROOT/'ui_huskar/qml/components').as_uri()+'''"
QtObject {
    function showTip(item, text) { HoverTip.showFor(item,text,12,12); }
    function state() { return JSON.stringify({visible:HoverTip.visible,x:HoverTip.x,y:HoverTip.y,width:HoverTip.width,height:HoverTip.height,html:HoverTip.html,parentWidth:HoverTip.parent.width,parentHeight:HoverTip.parent.height}); }
    function hideTip() { HoverTip.hide(); }
}''').encode(),QUrl())
harness=component.create();assert harness is not None,[x.toString() for x in component.errors()]
results=[]
for key in ('class_mod','enhancement','shield','repkit','heavy_weapon'):
    bridge.navigate(key);QTest.qWait(450)
    count=vms[key].prepareBackpackImport();assert count>0,key
    dialog=window.findChild(QObject,'backpackDialog');assert dialog is not None,key
    dialog.open();QTest.qWait(450)
    view=window.findChild(QObject,'backpackResults');assert view.property('count')==count
    window.grabWindow().save(str(out/(key+'-backpack.png')))
    search=window.findChild(QObject,'backpackSearch');search.setProperty('text','___no_match___');QTest.qWait(50)
    assert view.property('count')==0
    search.setProperty('text',vms[key].backpackItems[-1]['name']);QTest.qWait(50)
    assert view.property('count')>=1
    dialog.setProperty('selectedSource',count-1);dialog.importSelection();QTest.qWait(450)
    assert vms[key].importedCopy
    results.append(dict(page=key,count=count,search=True,imported=True))
bridge.navigate('enhancement');QTest.qWait(450)
assert main_menu.property('selectedKey') == 'enhancement'
enh_badge=window.findChild(QObject,'enhancementLegitIndicator');assert enh_badge is not None
assert enh_badge.property('status') in ('incomplete','legal','invalid','unknown','conditional')
enh_lucky=window.findChild(QObject,'enhancementLuckyRoll');assert enh_lucky is not None
enh_arrow=window.findChild(QObject,'enhancementLuckyArrow');assert enh_arrow is not None
enh_arrow.clicked.emit();QTest.qWait(120)
enh_popup=window.findChild(QObject,'enhancementRollOptions');assert enh_popup is not None and enh_popup.property('visible')
assert len(vms['enhancement'].rollConstraintOptions['manufacturers']) > 1
enh_popup.close();QTest.qWait(80)
enh_lucky.clicked.emit();QTest.qWait(1200);assert len(vms['enhancement'].rollResults)==5
assert all(row['status']=='legal' for row in vms['enhancement'].rollResults)
window.grabWindow().save(str(out/'enhancement-legit-layout.png'))
enh_dialog=window.findChild(QObject,'enhancementRollDialog');assert enh_dialog is not None;enh_dialog.close();QTest.qWait(80)
enh_page=window.findChild(QObject,'enhancementPage');assert enh_page is not None
enh_page.setProperty('contentY',560);QTest.qWait(120)
window.grabWindow().save(str(out/'enhancement-candidate-parts.png'))
bridge.navigate('class_mod');QTest.qWait(450)
assert main_menu.property('selectedKey') == 'class_mod'
class_badge=window.findChild(QObject,'classModLegitIndicator');assert class_badge is not None
assert class_badge.property('status') in ('incomplete','legal','invalid','unknown','conditional')
class_lucky=window.findChild(QObject,'classModLuckyRoll');assert class_lucky is not None
class_arrow=window.findChild(QObject,'classModLuckyArrow');assert class_arrow is not None
class_arrow.clicked.emit();QTest.qWait(120)
class_popup=window.findChild(QObject,'classModRollOptions');assert class_popup is not None and class_popup.property('visible')
assert len(vms['class_mod'].rollConstraintOptions['named_items']) > 1
class_popup.close();QTest.qWait(80)
class_lucky.clicked.emit();QTest.qWait(3000);assert len(vms['class_mod'].rollResults)==5
assert all(row['status']=='legal' for row in vms['class_mod'].rollResults)
window.grabWindow().save(str(out/'class-mod-legit-layout.png'))
class_dialog=window.findChild(QObject,'classModRollDialog');assert class_dialog is not None;class_dialog.close();QTest.qWait(80)
class_page=window.findChild(QObject,'classModPage');assert class_page is not None
class_page.setProperty('contentY',720);QTest.qWait(120)
window.grabWindow().save(str(out/'class-mod-candidate-parts.png'))
vms['class_mod'].resetSource();QTest.qWait(120)
class_page.setProperty('contentY',720);QTest.qWait(120)
window.grabWindow().save(str(out/'class-mod-candidate-default.png'))
bridge.navigate('enhancement');QTest.qWait(120)
vms['enhancement'].resetSource();QTest.qWait(120)
enh_page=window.findChild(QObject,'enhancementPage');enh_page.setProperty('contentY',0);QTest.qWait(120)
window.grabWindow().save(str(out/'enhancement-candidate-default.png'))
bridge.navigate('class_mod');QTest.qWait(120)
options=window.findChild(QObject,'optionsList');assert options is not None
tip=vms['class_mod'].skillOptions[0]['tooltip'];assert '<b>' in tip
harness.showTip(options,tip);QTest.qWait(500)
state=json.loads(harness.state());assert state['visible'] and state['height']>40,state
assert state['x']>=0 and state['x']+state['width']<=state['parentWidth'],state
assert state['y']>=0 and state['y']+state['height']<=state['parentHeight'],state
window.grabWindow().save(str(out/'skill-rich-hover.png'));harness.hideTip()
bridge.navigate('weapon_generator');QTest.qWait(450)
popup=window.findChild(QObject,'weaponRollOptions');assert popup is not None
# Open via the same button handler rather than bypassing constraint initialization.
arrow=window.findChild(QObject,'weaponRollArrow');arrow.clicked.emit();QTest.qWait(200)
window.grabWindow().save(str(out/'weapon-roll-options.png'));popup.close();QTest.qWait(450)
quick=window.findChild(QObject,'weaponQuickRoll');quick.clicked.emit();QTest.qWait(250)
assert vms['weapon_generator'].rollResults
window.grabWindow().save(str(out/'weapon-roll-results.png'))
results.append(dict(hover=state,roll_count=len(vms['weapon_generator'].rollResults),warnings=warnings))
(out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(results,ensure_ascii=False))
assert not warnings,warnings
engine.clearComponentCache();bridge.shutdown();window.close()
