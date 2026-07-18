# Translation Review — RU / UA

The strings below were newly routed through the localization JSON while
replacing hardcoded `if zh-CN else English` code (which only ever supported
two languages, so Russian and Ukrainian users saw English). The **zh** and
**en** values come verbatim from the original code. The **ru** and **ua**
values are **best-effort and need native review** — please correct any that
read awkwardly.

## weapon_editor_tab

| key | en | ru (review) | ua (review) |
|---|---|---|---|
| labels.search_weapon_placeholder | Search name, manufacturer, type, level, or slot | Поиск по имени, производителю, типу, уровню или слоту | Пошук за іменем, виробником, типом, рівнем або слотом |
| tooltips.refresh_parts | Refresh parts | Обновить детали | Оновити деталі |
| tooltips.change_skin | Change skin | Сменить облик | Змінити вигляд |
| tooltips.move_up | Move up | Вверх | Вгору |
| tooltips.move_down | Move down | Вниз | Вниз |
| tooltips.remove_part | Remove | Удалить | Видалити |
| parts.cosmetic_part | Cosmetic part | Косметическая деталь | Косметична деталь |
| parts.element_config | Element configuration | Настройка стихии | Налаштування стихії |
| parts.unnamed_barrel | Unnamed Barrel | Безымянный ствол | Безіменний ствол |
| parts.element_group | Element Configuration Group · {n} parts | Группа настройки стихии · {n} дет. | Група налаштування стихії · {n} дет. |
| parts.licensed_group | Licensed Part Group · {mfg} · {n} parts | Группа лицензир. деталей · {mfg} · {n} дет. | Група ліцензов. деталей · {mfg} · {n} дет. |
| summary.none_selected | No backpack weapon selected | Оружие из рюкзака не выбрано | Зброю з рюкзака не вибрано |
| summary.selected | Selected · {name} · Lv.{level} | Выбрано · {name} · Ур.{level} | Вибрано · {name} · Рів.{level} |
| summary.fallback_name | Weapon | Оружие | Зброя |
| catalog.search_part | Search part name, effect, manufacturer, or type | Поиск по названию, эффекту, производителю или типу | Пошук за назвою, ефектом, виробником або типом |
| catalog.available_parts | Available Parts | Доступные детали | Доступні деталі |
| catalog.selected_parts | Selected Parts | Выбранные детали | Вибрані деталі |
| catalog.clear | Clear | Очистить | Очистити |
| catalog.all | All | Все | Усі |
| catalog.all_manufacturers | All Manufacturers | Все производители | Усі виробники |
| catalog.all_weapon_types | All Weapon Types | Все типы оружия | Усі типи зброї |

## class_mod_tab

| key | en | ru (review) | ua (review) |
|---|---|---|---|
| perk_filters.all | All | Все | Усі |
| perk_filters.weapon | Weapon | Оружие | Зброя |
| perk_filters.skill | Skill | Навык | Навичка |
| perk_filters.element | Element | Стихия | Стихія |
| perk_filters.defense | Defense | Защита | Захист |
| perk_filters.utility | Utility | Утилита | Утиліта |
| perk_filters.firmware | Firmware | Прошивка | Прошивка |
| perk_filters.other | Other | Другое | Інше |
| skill_trees.red | Red | Красный | Червоний |
| skill_trees.green | Green | Зелёный | Зелений |
| skill_trees.blue | Blue | Синий | Синій |
| skill_trees.all_skills | All Skills | Все навыки | Усі навички |
| skill_trees.passive | Passive | Пассивный | Пасивний |
| legendary.search_placeholder | Search... | Поиск… | Пошук… |

## enhancement_tab

Category (`_CAT_LABELS`) and stat (`_SUB_LABELS`) filter taxonomies now carry
ru/ua in-code (co-located with the filter logic). Picker chrome added under
`enhancement_tab.picker`:

| key | en | ru (review) | ua (review) |
|---|---|---|---|
| picker.search_placeholder | Search... | Поиск… | Пошук… |
| picker.available | Available (double-click to add) | Доступно (двойной клик) | Доступно (подвійний клік) |
| picker.selected_stacks | Selected Stacks | Выбранные стопки | Вибрані стоси |
| picker.selected_stats | Selected Stats | Выбранные характеристики | Вибрані характеристики |
| _CAT_LABELS.* | All/Firmware/Sniper/Shotgun/SMG/Pistol/AR/Universal | Все/Прошивка/Снайперская/Дробовик/ПП/Пистолет/Автомат/Универсальный | Усі/Прошивка/Снайперська/Дробовик/ПП/Пістолет/Автомат/Універсальний |
| _SUB_LABELS.* | Damage/Crit DMG/Fire Rate/Accuracy/Reload/Magazine/Splash DMG/Splash Radius/ADS/SE DMG/SE Chance/Equip/Other | Урон/Крит. урон/Скорострельность/Точность/Перезарядка/Магазин/Урон по площади/Радиус поражения/Прицел/Урон статуса/Шанс статуса/Снаряжение/Другое | Урон/Крит. урон/Скорострільність/Точність/Перезарядка/Магазин/Урон по площі/Радіус ураження/Приціл/Урон статусу/Шанс статусу/Спорядження/Інше |
