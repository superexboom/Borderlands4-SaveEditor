import sys
sys.path.insert(0, r'C:\Users\SuperExboom\Desktop\BL4\sav_edit')
import core.decoder_logic as dl
import core.serial_inspect as si

s = '@Ugr$)Nm/*xI!sP#;L{(~iG&kgj#1T)D00'
print('serial:', s, 'len', len(s))
txt, blocks, err = dl.decode_serial_to_string(s)
print('decoded:', txt)
print('err:', err)
print()
info = si.inspect_serial(s, 'zh')
if isinstance(info, dict):
    for k in ('item_id', 'manufacturer', 'item_type', 'level', 'rarity', 'display_name'):
        print('  %-14s %s' % (k, info.get(k)))
    print()
    pr = info.get('part_rows') or info.get('parts') or []
    print('part_rows (%d):' % len(pr))
    for x in pr:
        if isinstance(x, dict):
            print('   key=%-8s cat=%-18s %s' % (
                x.get('key'), x.get('category'),
                str(x.get('name') or x.get('display') or x.get('stat') or '')[:50]))
