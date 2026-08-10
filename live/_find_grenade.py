import sys
sys.path.insert(0, r'C:\Users\SuperExboom\Desktop\BL4\sav_edit')
from live.bridge import Bridge

items = Bridge().read(container='BackpackItems')
prefix = '@Ugr$)Nm'
hits = [it for it in items if it.get('serial', '').startswith(prefix)]
print('total backpack items:', len([i for i in items if i.get('ok')]))
print('matches for prefix %r: %d' % (prefix, len(hits)))
for it in hits:
    print('  idx=%s serial=%s' % (it.get('idx'), it.get('serial')))
    print('    size=%s cap=%s parts=%s/%s' % (
        it.get('size'), it.get('capacity'), it.get('parts_num'), it.get('parts_max')))
