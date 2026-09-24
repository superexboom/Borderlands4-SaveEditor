"""Prepared inventory filters shared by Widgets and the QML preview."""


def prepare_item_search(item, container_label='', flag_label=''):
    values = {
        'container': str(item.get('container') or ''),
        'type': str(item.get('type_en') or item.get('type') or ''),
        'manufacturer': str(item.get('manufacturer_en') or item.get('manufacturer') or ''),
        'rarity': str(item.get('rarity_en') or item.get('rarity') or ''),
        'flags': str(item.get('state_flags') or ''),
    }
    values['text'] = ' '.join([
        *(str(item.get(key) or '') for key in (
            'name', 'base_name', 'type', 'type_en', 'manufacturer',
            'manufacturer_en', 'rarity', 'rarity_en', 'serial', 'decoded_full',
        )), container_label, flag_label,
    ]).casefold()
    try:
        values['level'] = int(item.get('level') or 0)
    except (TypeError, ValueError):
        values['level'] = 0
    return values


def matches_item_search(values, query, filters, minimum=0, maximum=0):
    return (
        (not query or query in values['text'])
        and all(values.get(key) == value for key, value in filters)
        and (not minimum or values['level'] >= minimum)
        and (not maximum or values['level'] <= maximum)
    )
