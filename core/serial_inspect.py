"""Read-only analysis of a single item serial.

``inspect_serial`` accepts either a Base85 code or an already decoded string and
returns one flat dict describing everything the project knows about that item.
It never raises and never mutates save state, so callers can feed it arbitrary
pasted text.

Part enumeration deliberately reuses :func:`weapon_display_stats._serial_part_keys`
because that is the enumeration the item cards and stat resolvers agree on. The
project contains three other component regexes; picking a different one makes
the part list disagree with the rendered card.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from core import b_encoder, bl4_functions, decoder_logic, lookup, resource_loader
from core import item_display_resolver as resolver
from core import weapon_display_stats
from core.item_display_resolver import HEAVY_TYPE, WEAPON_TYPES

__all__ = ["inspect_serial", "part_rows", "bit_layout", "NO_STAT_TEXTS"]

EMBEDDED_SERIAL_CATALOG = "core/data/embedded_serial_catalog.json"

_CATALOG_ENTRY_FIELDS = {
    "serial", "base85", "decoded", "canonical_decoded", "root_ref",
    "composition_ref", "name", "type", "level", "source_kind", "source_file",
    "object_name", "field", "context", "provenance", "latest_present",
    "add_allowed", "warnings", "canonical_refs", "component_refs", "part_refs",
    "display_name", "internal_refs", "refs", "parts", "preferred_parts",
}

_PROVENANCE_TAG_ORDER = (
    "official_loadout", "mission", "npc", "skill", "ui", "historical", "orphan"
)

# format_weapon_part_description returns this literal both for parts that truly
# have no stats and for parts whose payload cannot be rendered. Inspector output
# distinguishes the two by checking the ref payload directly.
NO_STAT_TEXTS = {"无属性变化", "No stat changes"}

# Exact strings produced by lookup.get_kind_enums / dynamic_item_kind. Only
# these four have an entry in equipment_native_models.models, which is what
# _family_model resolves against (equipment_display_stats.FAMILY_BY_ITEM_TYPE);
# resolve_equipment_stats gates on the same set.
_EQUIPMENT_STAT_TYPES = {"Shield", "Grenade", "Repkit", HEAVY_TYPE}

# Enhancement and Class Mod roots are absent from every equipment family, so
# _family_model always raises and format_equipment_part_description can only
# return "". Their per-part text lives in the whole-item CSV resolvers, both of
# which tag each entry with the part id it came from.
_CSV_DETAIL_TYPES = {"Enhancement", "Class Mod"}

# Owner of the shared Class Mod perk/firmware pool. It has no part_refs entry
# (the pipeline's shared_roots set omits "classmod"), so these tokens can only
# be named through class_mods/Class_perk.csv via resolve_classmod_card_details.
_CLASSMOD_SHARED_OWNER = "234"

# A value slot the CSV resolver was supposed to fill, e.g. "弹匣容量增加{mod}".
# Matches only bare word placeholders, so localized text containing braces for
# other reasons is left alone.
_UNFILLED_PLACEHOLDER_RE = re.compile(r"\{\w+\}")

# Repkit elemental mechanics carriers. Each of the four effect families has a
# primary and a secondary slot variant, and the effect parts themselves supply
# the visible text ("Preheat: +50% cryo resistance for 15s"), so these carry
# uistats: [] and would otherwise render as a blank row. Their values live in
# RepKit_AugmentData, reachable only through datatable_refs, which no exporter
# resolves; the loc key below names the mechanism instead of inventing numbers.
# Verified over 592 repkit samples (245 epic / 151 legendary / 196 CT): every
# elemental effect part co-occurs with exactly one of its family's two carriers,
# and every carrier co-occurs with an effect part - zero counterexamples.
_ELEMENTAL_CARRIERS = {
    "243:53": "elemental_resist_base",
    "243:76": "elemental_resist_base",
    "243:55": "elemental_immunity_base",
    "243:78": "elemental_immunity_base",
    "243:72": "elemental_splat_base",
    "243:95": "elemental_splat_base",
    "243:66": "elemental_nova_base",
    "243:89": "elemental_nova_base",
}

_ELEMENTAL_CARRIER_FALLBACK = {
    "elemental_resist_base": {"zh": "元素抗性基座", "en": "Elemental Resistance Base"},
    "elemental_immunity_base": {"zh": "元素免疫基座", "en": "Elemental Immunity Base"},
    "elemental_splat_base": {"zh": "元素喷溅基座", "en": "Elemental Splat Base"},
    "elemental_nova_base": {"zh": "元素新星基座", "en": "Elemental Nova Base"},
}

_ELEMENTAL_CARRIER_CATEGORIES = {
    "elemental_resist_base": "augment_element_resist",
    "elemental_immunity_base": "augment_element_immunity",
    "elemental_splat_base": "augment_element_splat",
    "elemental_nova_base": "augment_element_nova",
}

_ELEMENT_LABELS = {
    "normal": {"zh": "无元素", "en": "No Element"},
    "corrosive": {"zh": "腐蚀", "en": "Corrosive"},
    "cryo": {"zh": "冰冻", "en": "Cryo"},
    "fire": {"zh": "燃烧", "en": "Incendiary"},
    "radiation": {"zh": "辐射", "en": "Radiation"},
    "shock": {"zh": "电击", "en": "Shock"},
    "kinetic": {"zh": "动能", "en": "Kinetic"},
    "sonic": {"zh": "声波", "en": "Sonic"},
}

_SHIELD_PART_SUBTYPES = {"237": "armor", "248": "energy"}


@lru_cache(maxsize=8)
def _carrier_labels(lang: str) -> dict[str, str]:
    """Localized carrier names, falling back to the built-in zh/en pair."""
    try:
        loc = resource_loader.load_json_resource(
            resource_loader.get_ui_localization_file(lang)
        ) or {}
        table = ((loc.get("serial_inspector_tab") or {}).get("part_carriers")) or {}
    except Exception:
        table = {}
    zh = resolver._lang_is_zh(lang)
    out: dict[str, str] = {}
    for key, pair in _ELEMENTAL_CARRIER_FALLBACK.items():
        value = str(table.get(key) or "").strip()
        out[key] = value or pair["zh" if zh else "en"]
    return out


def _blank(text: str) -> bool:
    return not text or not text.strip()


def _element_part_label(ref: dict[str, Any], item_type: str, lang: str) -> str:
    part = str(ref.get("part") or "").casefold()
    element = next(
        (name for name in _ELEMENT_LABELS if f"_{name}" in part or part.endswith(name)),
        "",
    )
    if not element:
        return ""
    label = _ELEMENT_LABELS[element]["zh" if resolver._lang_is_zh(lang) else "en"]
    if item_type == "Shield" and element == "normal":
        return "无元素抗性" if resolver._lang_is_zh(lang) else "No Elemental Resistance"
    return label


def _gold_skin_selected(item_id: int, item_type: str, rows: list[dict[str, Any]]) -> bool:
    selected = {str(row.get("key") or "") for row in rows}
    try:
        catalog = resolver._csv_rows_for_type(item_type)
    except (KeyError, OSError, TypeError, ValueError):
        return False
    for row in catalog:
        if str(row.get("Part_type") or "").casefold() != "rarity":
            continue
        if str(row.get("Description_EN") or "").strip().casefold() != "gold skin":
            continue
        ref_key = f"{row.get('Manufacturer ID')}:{row.get('Part_ID')}"
        if str(row.get("Manufacturer ID") or "") == str(item_id) and ref_key in selected:
            return True
    return False


def _shield_subtype(generation: dict[str, Any]) -> str:
    weapon_type = str(generation.get("weapon_type") or "").casefold()
    if "energy" in weapon_type:
        return "energy"
    if "armor" in weapon_type:
        return "armor"
    return ""


def _annotate_shield_violations(
    violations: list[dict[str, Any]], subtype: str
) -> list[dict[str, Any]]:
    if not subtype:
        return violations
    annotated: list[dict[str, Any]] = []
    for violation in violations:
        item = dict(violation)
        refs = [str(item.get("part") or ""), *(str(ref) for ref in item.get("parts") or [])]
        incompatible = {
            part_type
            for ref in refs
            if (part_type := _SHIELD_PART_SUBTYPES.get(ref.partition(":")[0]))
            and part_type != subtype
        }
        if len(incompatible) == 1:
            item["shield_type"] = subtype
            item["incompatible_shield_type"] = incompatible.pop()
        annotated.append(item)
    return annotated


def _decode_any(text: str) -> tuple[str, str, str]:
    """Return ``(decoded_full, base85, error)`` from either input form."""
    raw = (text or "").strip()
    if _blank(raw):
        return "", "", "empty"
    if "||" in raw:
        decoded = raw
        try:
            encoded, err = b_encoder.encode_to_base85(decoded)
            return decoded, ("" if err else encoded), ""
        except Exception:
            return decoded, "", ""
    candidate = raw.split()[0] if raw.split() else raw
    try:
        decoded, _blocks, err = decoder_logic.decode_serial_to_string(candidate)
    except Exception as exc:  # pragma: no cover - defensive
        return "", candidate, f"{type(exc).__name__}: {exc}"
    if err or _blank(decoded):
        return "", candidate, err or "decode produced no output"
    return decoded.strip(), candidate, ""


def _collect_catalog_entries(
    node: Any,
    group: str,
    path: tuple[str, ...],
    out: list[dict[str, Any]],
) -> None:
    if isinstance(node, dict):
        if _CATALOG_ENTRY_FIELDS.intersection(node):
            entry = dict(node)
            if group == "preferred_parts":
                entry.setdefault("composition_ref", path[-1] if path else "")
                entry.setdefault("source_kind", "rules_only")
                entry["add_allowed"] = False
                entry.setdefault("preferred_parts", entry.get("refs") or entry.get("parts") or [])
                entry.setdefault("_catalog_group", "rules_only")
            else:
                entry.setdefault("_catalog_group", group)
            entry.setdefault("_catalog_path", "/".join(path))
            out.append(entry)
            return
        for key, value in node.items():
            _collect_catalog_entries(value, group, (*path, str(key)), out)
        return
    if isinstance(node, list):
        if group == "preferred_parts" and node and all(not isinstance(value, (dict, list)) for value in node):
            label = path[-1] if path else "preferred_parts"
            out.append({
                "name": label,
                "composition_ref": label if "." in label else "",
                "preferred_parts": [str(value) for value in node],
                "source_kind": "rules_only",
                "add_allowed": False,
                "_catalog_group": "rules_only",
                "_catalog_path": "/".join(path),
            })
            return
        for index, value in enumerate(node):
            _collect_catalog_entries(value, group, (*path, str(index)), out)


def _normalize_catalog_groups(
    data: dict[str, Any] | None, groups: tuple[str, ...]
) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    entries: list[dict[str, Any]] = []
    for group in groups:
        _collect_catalog_entries(data.get(group), group, (group,), entries)
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for entry in entries:
        key = tuple(str(entry.get(name) or "") for name in (
            "serial", "base85", "decoded", "composition_ref", "source_kind",
            "source_file", "object_name", "field", "_catalog_group", "_catalog_path",
        ))
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def normalize_embedded_catalog(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten all provenance entries while tolerating additive schema changes."""
    return _normalize_catalog_groups(data, ("presets", "current", "history", "preferred_parts"))


def normalize_embedded_presets(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Only user-facing presets and rule-only compositions, without 53/88 duplicates."""
    rows = _normalize_catalog_groups(data, ("presets", "preferred_parts"))
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, row in enumerate(rows):
        identity = str(row.get("serial") or row.get("base85") or row.get("composition_ref") or f"row:{index}")
        if identity not in merged:
            merged[identity] = dict(row)
            order.append(identity)
            continue
        current = merged[identity]
        for key in ("preferred_parts", "refs", "parts", "canonical_refs", "internal_refs", "variants"):
            if not current.get(key) and row.get(key):
                current[key] = row[key]
    return [merged[key] for key in order]


@lru_cache(maxsize=1)
def embedded_serial_catalog() -> dict[str, Any]:
    data = resource_loader.load_json_resource(EMBEDDED_SERIAL_CATALOG)
    return dict(data) if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def embedded_serial_entries() -> tuple[dict[str, Any], ...]:
    return tuple(normalize_embedded_catalog(embedded_serial_catalog()))


@lru_cache(maxsize=1)
def embedded_serial_preset_entries() -> tuple[dict[str, Any], ...]:
    return tuple(normalize_embedded_presets(embedded_serial_catalog()))


def catalog_matches_for_serial(base85: str, decoded: str) -> list[dict[str, Any]]:
    base85 = str(base85 or "").strip()
    decoded = str(decoded or "").strip()
    matches = []
    for entry in embedded_serial_entries():
        entry_serial = str(entry.get("serial") or entry.get("base85") or "").strip()
        entry_decoded = str(entry.get("decoded") or "").strip()
        if (base85 and entry_serial == base85) or (decoded and entry_decoded == decoded):
            matches.append(dict(entry))
    priority = {"presets": 0, "current": 1, "history": 2, "rules_only": 3}
    return sorted(matches, key=lambda entry: priority.get(str(entry.get("_catalog_group")), 9))


def catalog_provenance_tags(entries: list[dict[str, Any]]) -> list[str]:
    tags: set[str] = set()
    has_latest = any(
        str(entry.get("_catalog_group") or "") in {"current", "presets"}
        or entry.get("latest_present") is True
        for entry in entries
    )
    for entry in entries:
        group = str(entry.get("_catalog_group") or "").casefold()
        kind = str(entry.get("source_kind") or "").casefold()
        context = str(entry.get("context") or "").casefold()
        semantic_provenance: list[str] = []
        provenance = entry.get("provenance") or []
        if isinstance(provenance, str):
            semantic_provenance.append(provenance)
        elif isinstance(provenance, dict):
            provenance = [provenance]
        if isinstance(provenance, list):
            for row in provenance:
                if not isinstance(row, dict):
                    continue
                semantic_provenance.extend(
                    str(row.get(key) or "")
                    for key in ("source_kind", "logical_kind", "source_file", "object_name", "context")
                )
        raw_warnings = entry.get("warnings") or []
        if isinstance(raw_warnings, str):
            raw_warnings = [raw_warnings]
        warnings = " ".join(str(value) for value in raw_warnings).casefold()
        blob = " ".join((
            group,
            kind,
            str(entry.get("source_file") or ""),
            str(entry.get("object_name") or ""),
            context,
            *semantic_provenance,
            warnings,
        )).casefold()
        if not has_latest and (group == "history" or entry.get("latest_present") is False or "histor" in blob):
            tags.add("historical")
        if "orphan" in blob or "unused" in blob or "legacy" in blob:
            tags.add("orphan")
        if any(token in blob for token in ("profile_default", "starter", "loadout", "prologue", "uvhm")):
            tags.add("official_loadout")
        if re.search(r"(?:^|[^a-z0-9])(mission|quest|story)(?:$|[^a-z0-9])", blob):
            tags.add("mission")
        if any(token in blob for token in ("skill_actor", "skill weapon", "turret", "phase")):
            tags.add("skill")
        if any(token in blob for token in ("ui_preview", "uiwidget", "menu preview")):
            tags.add("ui")
        if any(token in blob for token in ("npc", "actor", "cinematic", "cine", "enemy", "marketing")):
            tags.add("npc")
    return [tag for tag in _PROVENANCE_TAG_ORDER if tag in tags]


def catalog_rules_for_composition(aliases: list[str]) -> list[dict[str, Any]]:
    wanted = {str(alias or "").strip().casefold() for alias in aliases if str(alias or "").strip()}
    if not wanted:
        return []
    matches: list[dict[str, Any]] = []
    for entry in embedded_serial_preset_entries():
        if not entry.get("preferred_parts") and str(entry.get("_catalog_group") or "") != "rules_only":
            continue
        candidates = {
            str(entry.get("composition_ref") or "").strip().casefold(),
            str(entry.get("name") or "").strip().casefold(),
            str(entry.get("_catalog_path") or "").rsplit("/", 1)[-1].strip().casefold(),
        }
        if wanted.intersection(candidates):
            matches.append(dict(entry))
    return matches


def _kind(item_id: int) -> tuple[str, str, bool]:
    manufacturer, item_type, found = lookup.get_kind_enums(item_id)
    if found:
        return manufacturer, item_type, True
    dynamic = resolver.dynamic_item_kind(item_id)
    if dynamic:
        return dynamic[0], dynamic[1], True
    return "", "", False


def _ref_payload(ref: dict[str, Any]) -> int:
    """Count only payload entries a formatter is expected to turn into text.

    A plain length sum reports "unmapped" for every part whose payload is
    deliberately dropped downstream. Two kinds are dropped: attributes listed in
    WEAPON_PART_INTERNAL_ATTRIBUTES (engine-internal, skipped by
    _part_direct_effects) and modifiers with no attribute, stat tag or source
    aspect to attribute the number to (equipment_display_stats._stat_groups
    needs one of those to place a modifier).
    """
    effects = [
        effect
        for effect in (ref.get("weapon_attribute_effects") or [])
        if str(effect.get("attribute") or "").casefold()
        not in resolver.WEAPON_PART_INTERNAL_ATTRIBUTES
    ]
    modifiers = [
        modifier
        for modifier in (ref.get("weapon_stat_modifiers") or [])
        if modifier.get("attr") or modifier.get("stat_tag") or modifier.get("source_aspect")
    ]
    # Mirror the uistats precedence used by equipment_part_name and
    # equipment_part_uistat_descriptions.
    uistats = ref.get("uistats_include") or ref.get("uistats") or []
    return len(effects) + len(modifiers) + len(uistats)


def _plain_markup(value: Any) -> str:
    """Strip the game's localized markup without producing HTML.

    render_skill_markup emits <span style=...> for the same input, which is right
    for the card but wrong for a table cell: the inspector's part table renders
    plain text, so the tags would show up verbatim.
    """
    text = str(value or "").replace("[newline]", " ").replace("\n", " ")
    text = re.sub(r"\[/?[a-z][a-z0-9_]*\]", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=64)
def _classmod_skill_tiers(item_id: int) -> dict[str, int]:
    """Map a Class Mod part id to the skill rank it grants.

    Skills.csv has no tier column, but each row lists five part ids in
    skill_ID_1..skill_ID_5, and the column index is the rank: selecting the id in
    skill_ID_3 puts the skill at rank 3. Part ids are unique per class_ID, so the
    mapping is unambiguous within one item.
    """
    tiers: dict[str, int] = {}
    for row in resolver._rows_by_file("class_mods/Skills.csv"):
        if (row.get("class_ID") or "").strip() != str(item_id):
            continue
        for rank in range(1, 6):
            code = (row.get(f"skill_ID_{rank}") or "").strip()
            if code:
                tiers[code] = rank
    return tiers


def _csv_part_details(
    decoded_full: str, item_id: int, item_type: str, lang: str
) -> dict[str, dict[str, str]]:
    """Map ref_key -> {text, name, category} for the types with no equipment model.

    Enhancement and Class Mod cards are built from whole-item CSV resolvers
    rather than a native stat model, but both already report which part id each
    entry came from, so the per-part view can be reconstructed from them. The
    name and category are carried along because the shared Class Mod perk owner
    has no part_refs row to read them from.
    """
    out: dict[str, dict[str, str]] = {}
    if item_type == "Enhancement":
        try:
            details = resolver.resolve_enhancement_card_details(decoded_full, lang) or {}
        except Exception:
            return out
        for entry in details.get("effects") or []:
            out[f"{item_id}:{entry.get('id')}"] = {"text": _plain_markup(entry.get("text"))}
        for entry in details.get("stacked_effects") or []:
            text = _plain_markup(entry.get("text"))
            count = int(entry.get("count") or 1)
            out[f"{entry.get('manufacturer_id')}:{entry.get('id')}"] = {
                "text": f"{text} x{count}" if count > 1 else text
            }
        # Secondary stats and firmware are always resolved against shared owner 247.
        for entry in details.get("stats") or []:
            out[f"247:{entry.get('id')}"] = {
                "text": _plain_markup(entry.get("text") or "")
            }
        for entry in details.get("firmware") or []:
            ref_key = f"247:{entry.get('id')}"
            out[ref_key] = _firmware_csv_detail(ref_key, item_type, lang, entry)
        return out

    if item_type == "Class Mod":
        try:
            # The default skill_limit of 6 truncates the list; the inspector
            # needs every skill the serial actually selected.
            details = resolver.resolve_classmod_card_details(decoded_full, lang, 64) or {}
        except Exception:
            return out
        tiers = _classmod_skill_tiers(item_id)
        for skill in details.get("skills") or []:
            lines = [_plain_markup(line) for line in (skill.get("stat_lines") or [])]
            codes = skill.get("selected_codes") or []
            max_points = int(skill.get("max_points") or 0)
            for code in codes:
                # One row per part, so the rank has to be this part's own rank,
                # not the skill's total. Skills.csv has no tier column, but its
                # skill_ID_1..skill_ID_5 columns are the ranks: the column a part
                # id sits in is the rank that part grants. The card shows the
                # summed total instead, which is right for the card and wrong here.
                tier = tiers.get(str(code))
                head = f"+{tier}/{max_points}" if tier and max_points else ""
                out[f"{item_id}:{code}"] = {
                    "text": ", ".join(part for part in [head, *lines] if part and part.strip()),
                    "name": _plain_markup(skill.get("name")),
                }
        for entry in details.get("perks") or []:
            name = _plain_markup(entry.get("name") or entry.get("text") or "")
            # No "xN" suffix: the card collapses duplicate perks into one line and
            # reports the count, but here each copy already has its own row.
            out[f"{_CLASSMOD_SHARED_OWNER}:{entry.get('id')}"] = {
                "text": name,
                "name": name,
                "category": str(entry.get("category") or ""),
                "part": str(entry.get("internal") or ""),
            }
        for entry in details.get("firmware") or []:
            ref_key = f"{_CLASSMOD_SHARED_OWNER}:{entry.get('id')}"
            out[ref_key] = _firmware_csv_detail(ref_key, item_type, lang, entry)
        # Legendary class mod bodies carry the item-wide effect text and red text.
        body_text = ", ".join(
            part
            for part in (
                _plain_markup(entry.get("text")) for entry in details.get("effects") or []
            )
            if part and part.strip()
        )
        if body_text:
            refs = resolver._item_index().get("part_refs") or {}
            for ref_key, ref in refs.items():
                if ref_key.startswith(f"{item_id}:") and ref.get("category") == "class_mod_body":
                    out.setdefault(ref_key, {"text": body_text})
        return out

    return out


def _firmware_csv_detail(
    ref_key: str,
    item_type: str,
    lang: str,
    fallback: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Use the shared firmware catalog for Inspector names and all three tiers."""
    try:
        entry = resolver.equipment_firmware_entry(ref_key, item_type, lang)
    except (KeyError, OSError, TypeError, ValueError):
        entry = None
    entry = entry or fallback or {}
    name = _plain_markup(entry.get("name") or entry.get("text") or "")
    descriptions = [
        f"L{level}: {_plain_markup(text)}"
        for level, text in enumerate(entry.get("descs") or [], 1)
        if _plain_markup(text)
    ]
    return {
        "text": ", ".join(descriptions) or name,
        "name": name,
        "category": "firmware",
        "part": str(entry.get("internal") or ""),
    }


def part_rows(decoded_full: str, item_id: int, item_type: str, lang: str = "zh-CN") -> list[dict[str, Any]]:
    """One row per part token, in serial order."""
    try:
        component = decoded_full.split("||", 1)[1]
    except (AttributeError, IndexError):
        return []
    try:
        keys = weapon_display_stats._serial_part_keys(component, str(item_id))
    except Exception:
        return []

    index = resolver._item_index()
    refs = index.get("part_refs") or {}
    is_weapon = item_type in WEAPON_TYPES
    # Heavy Weapon's card is built from the equipment model, so its per-part rows
    # must prefer the equipment formatter's final values ("Splash Radius 236cm")
    # over the weapon formatter's raw multipliers ("Splash Radius x1.24"). Its
    # inv_comp and barrel rows only resolve on the weapon side, so that stays as
    # the fallback rather than being dropped.
    is_heavy = item_type == HEAVY_TYPE
    csv_details = _csv_part_details(decoded_full, item_id, item_type, lang)
    rows: list[dict[str, Any]] = []
    for key in keys:
        owner, _, part_id = key.partition(":")
        ref = refs.get(key) or {}
        names = ref.get("name") or {}
        detail = csv_details.get(key) or {}
        # The shared Class Mod perk owner has no part_refs row, so its category
        # and internal part name can only come from the CSV resolver.
        category = str(ref.get("category") or detail.get("category") or "")
        carrier = _ELEMENTAL_CARRIERS.get(key)
        display_category = (
            "manufacturer_perk"
            if item_type == "Grenade" and category == "body"
            else _ELEMENTAL_CARRIER_CATEGORIES.get(carrier, category)
        )
        payload = _ref_payload(ref)

        description = ""
        if item_type in _EQUIPMENT_STAT_TYPES:
            # This helper resolves each referenced attribute id through the
            # family's attribute_resolvers and does the leave-one-out delta.
            try:
                description = (
                    resolver.format_equipment_part_description(
                        decoded_full, item_type, key, lang, strict_delta=True
                    )
                    or ""
                ).strip()
            except Exception:
                description = ""
        elif item_type in _CSV_DETAIL_TYPES:
            description = str(detail.get("text") or "").strip()

        if _blank(description) or description in NO_STAT_TEXTS:
            # The weapon formatter is the only source of text for a handful of
            # refs that gear serials also reference: intrinsic bodies (247:76,
            # 285:2, 321:10 ...) and the body_acc reload parts 12:3 / 3:4. Let
            # every item type fall back to it rather than leave the row blank.
            try:
                candidate = (
                    resolver.format_weapon_part_description(
                        int(owner),
                        part_id,
                        decoded_full,
                        lang,
                        # The 5th argument is the CSV "Part Type" column, not the
                        # index category, so it has to be title case to hit the
                        # intrinsic-part short circuit.
                        "Body" if category == "body" else "",
                    )
                    or ""
                ).strip()
            except Exception:
                candidate = ""
            if candidate and not (is_weapon or is_heavy):
                # On gear this is a fallback, not the owner of the text, so only
                # take a real statement. "No stat changes" would replace a clean
                # blank with noise on 1789 cosmetic rows, and an unsubstituted
                # template would reintroduce the {mod} leak fixed in 0de99b2.
                if candidate in NO_STAT_TEXTS or _UNFILLED_PLACEHOLDER_RE.search(candidate):
                    candidate = ""
            if candidate:
                description = candidate

        if _blank(description) or description in NO_STAT_TEXTS:
            # Elemental carriers legitimately have no stats of their own; name the
            # mechanism rather than leaving a blank row or claiming "no changes".
            if carrier:
                description = _carrier_labels(lang).get(carrier, "")

        if key == "243:104" and (_blank(description) or description in NO_STAT_TEXTS):
            description = (
                "基准治疗载荷（治疗量、持续时间与冷却均为 1x）"
                if resolver._lang_is_zh(lang)
                else "Baseline healing payload (1x healing, duration and cooldown)"
            )

        if description in NO_STAT_TEXTS or _blank(description):
            # Separate "genuinely cosmetic" from "payload present but unmapped".
            effect_state = "unmapped" if payload else "cosmetic"
        else:
            effect_state = "described"

        display_name = ""
        # weapon_part_name despite its name is the better namer for every item
        # type: it returns the curated ref["name"] on all 802 refs that have one,
        # covers 9 equipment refs equipment_part_name misses (and none the other
        # way). equipment_part_name puts the uistat title first, which collapses
        # distinct parts onto a shared group label: all 10 of 243:22..26,47 become
        # "元素抗性" where weapon_part_name keeps 橡胶/含铅/淬炼.
        # Both namers used to leak {mod}/{damage} placeholders on the 293 stat_group
        # refs of the shared 234/247 pools; _title_from_text now takes the label out
        # of the uistat markup instead of using the whole template sentence.
        try:
            display_name = resolver.weapon_part_name(int(owner), part_id, lang) or ""
        except Exception:
            display_name = ""
        if _blank(display_name):
            display_name = str(
                names.get("zh" if resolver._lang_is_zh(lang) else "en") or names.get("en") or ""
            ).strip()
        if _blank(display_name):
            display_name = str(detail.get("name") or "").strip()
        if _blank(display_name) and category in {"element", "body_ele"}:
            display_name = _element_part_label(ref, item_type, lang)
        if _blank(display_name) and carrier:
            display_name = _carrier_labels(lang).get(carrier, "")
        if _blank(display_name) and category == "firmware":
            # Firmware names live in the shared catalog (equipment_part_name resolves
            # them via the internal part string); the index itself carries no name.
            try:
                display_name = resolver.equipment_part_name(key, lang) or ""
            except Exception:
                display_name = ""

        rows.append(
            {
                "key": key,
                "owner": owner,
                "part_id": part_id,
                # 234:* perks resolve through Class_perk.csv even though the
                # shipped index has no part_refs row for them, so they are known.
                "known": bool(ref) or bool(detail),
                "category": category,
                "display_category": display_category,
                "part": str(ref.get("part") or detail.get("part") or ""),
                "rarity": str(ref.get("rarity") or ""),
                "name": display_name,
                "name_en": str(names.get("en") or ""),
                "name_zh": str(names.get("zh") or ""),
                "description": description,
                "effect_state": effect_state,
                "payload_count": payload,
                "uistats": list(ref.get("uistats_include") or ref.get("uistats") or []),
                "weapon_tags": list(ref.get("weapon_tags") or []),
                "stat_modifiers": list(ref.get("weapon_stat_modifiers") or []),
                "attribute_effects": list(ref.get("weapon_attribute_effects") or []),
            }
        )
    return rows


def bit_layout(base85: str) -> dict[str, Any]:
    """Per-block bit ranges of the raw serial.

    This mirrors ``b4s.serial.deserialize`` rather than calling ``next_token``
    in a loop: a token is only its 2-3 bit prefix, so the payload readers must
    run too or every payload bit gets misread as another token.
    """
    out: dict[str, Any] = {
        "available": False,
        "total_bits": 0,
        "total_bytes": 0,
        "header_bits": 0,
        "consumed_bits": 0,
        "padding_bits": 0,
        "blocks": [],
        "error": "",
    }
    if _blank(base85):
        out["error"] = "no base85"
        return out
    try:
        from bl4_decoder_py.b4s.serial_datatypes.b4string.read import read_b4string
        from bl4_decoder_py.b4s.serial_datatypes.part.read import read_part
        from bl4_decoder_py.b4s.serial_datatypes.varbit.read import read_varbit
        from bl4_decoder_py.b4s.serial_datatypes.varint.read import read_varint
        from bl4_decoder_py.b4s.serial_tokenizer.tokenizer import Token, Tokenizer

        data = decoder_logic.decode(base85.strip())
        out["total_bytes"] = len(data)
        tokenizer = Tokenizer(data)
        reader = tokenizer.bit_reader()
        out["total_bits"] = len(reader)

        tokenizer.expect("magic header", 0, 0, 1, 0, 0, 0, 0)
        out["header_bits"] = reader.get_pos()

        blocks: list[dict[str, Any]] = []
        while len(blocks) < 4096:
            start = reader.get_pos()
            try:
                token = tokenizer.next_token()
            except EOFError:
                break
            entry: dict[str, Any] = {
                "index": len(blocks),
                "token": token.name,
                "bit_start": start,
                "byte_start": start // 8,
                "value": None,
                "text": "",
            }
            if token == Token.TOK_VARINT:
                entry["value"] = read_varint(reader)
                entry["text"] = f"{{{entry['value']}}}"
            elif token == Token.TOK_VARBIT:
                entry["value"] = read_varbit(reader)
                entry["text"] = f"{{{entry['value']}}}"
            elif token == Token.TOK_PART:
                part = read_part(tokenizer)
                entry["value"] = part.index
                entry["sub_type"] = part.sub_type.name
                entry["values"] = list(part.values)
                if part.values:
                    entry["text"] = f"{{{part.index}:[{' '.join(str(v) for v in part.values)}]}}"
                elif part.sub_type.name == "SUBTYPE_INT":
                    entry["text"] = f"{{{part.index}:{part.value}}}"
                else:
                    entry["text"] = f"{{{part.index}}}"
            elif token == Token.TOK_STRING:
                entry["text"] = read_b4string(reader)
            entry["bit_end"] = reader.get_pos()
            entry["bit_len"] = max(0, entry["bit_end"] - start)
            blocks.append(entry)

        out["blocks"] = blocks
        out["consumed_bits"] = reader.get_pos()
        out["padding_bits"] = max(0, out["total_bits"] - out["consumed_bits"])
        out["available"] = bool(blocks)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _roundtrip(decoded_full: str, base85: str) -> dict[str, Any]:
    result = {"ok": False, "encoded": "", "matches_input": False, "error": ""}
    try:
        encoded, err = b_encoder.encode_to_base85(decoded_full)
        if err:
            result["error"] = str(err)
            return result
        result["encoded"] = encoded
        result["ok"] = bool(encoded)
        if base85:
            result["matches_input"] = encoded.strip() == base85.strip()
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def inspect_serial(text: str, lang: str = "zh-CN") -> dict[str, Any]:
    """Analyse one serial. Always returns a dict; ``ok`` reports usability."""
    report: dict[str, Any] = {
        "ok": False,
        "error": "",
        "input": (text or "").strip(),
        "base85": "",
        "decoded_full": "",
        "canonical_decoded": "",
        "decoded_parts": "",
        "canonical_parts": "",
        "serial_root": "",
        "item_id": None,
        "manufacturer": "",
        "manufacturer_en": "",
        "type": "",
        "type_en": "",
        "level": None,
        "seed": None,
        "implicit_level_one": False,
        "display_name": "",
        "rarity": "",
        "display_source": "",
        "display": {},
        "weapon_stats": {},
        "equipment_stats": {},
        "parts": [],
        "part_counts": {},
        "bit_layout": {},
        "roundtrip": {},
        "generation": {},
        "status": "",
        "equipment_subtype": "",
        "guidance_suppressed": "",
        "source_provenance": {"tags": [], "entries": []},
        "catalog_rules": [],
        "violations": [],
        "warnings": [],
    }

    decoded, base85, error = _decode_any(text)
    report["base85"] = base85
    report["decoded_full"] = decoded
    catalog_matches = catalog_matches_for_serial(base85, decoded)
    report["source_provenance"] = {
        "tags": catalog_provenance_tags(catalog_matches),
        "entries": catalog_matches,
    }
    if error or _blank(decoded):
        report["error"] = error or "could not decode input"
        return report

    header = bl4_functions.parse_decoded_item_header(decoded)
    if not header:
        report["error"] = "header parse failed"
        return report

    item_id = header["mfg_id"]
    report["item_id"] = item_id
    report["serial_root"] = str(header.get("root_token") or item_id)
    report["level"] = header.get("level")
    report["seed"] = header.get("seed")
    report["implicit_level_one"] = bool(header.get("implicit_level_one"))
    report["decoded_parts"] = str(header.get("component") or "").strip()

    catalog_entry = catalog_matches[0] if catalog_matches else None
    canonical_decoded, unresolved_tokens = resolver.canonicalize_decoded_serial(
        decoded, item_id, catalog_entry
    )
    report["canonical_decoded"] = canonical_decoded
    report["canonical_parts"] = canonical_decoded.split("||", 1)[1].strip() if "||" in canonical_decoded else ""
    if unresolved_tokens:
        report["warnings"].append(
            "unresolved string components: " + ", ".join(dict.fromkeys(unresolved_tokens))
        )

    composition_aliases = [
        str(entry.get("composition_ref") or "") for entry in catalog_matches
    ]
    try:
        context = resolver.weapon_generation_context(canonical_decoded)
        composition_refs = [
            *(context.get("composition_tokens") or []),
            *(context.get("unknown_compositions") or []),
        ]
        part_refs = resolver._item_index().get("part_refs") or {}
        composition_aliases.extend(str(ref) for ref in composition_refs)
        for ref in composition_refs:
            item = part_refs.get(str(ref)) or {}
            parent = str(item.get("parent") or "").strip()
            part = str(item.get("part") or "").strip()
            if parent and part:
                composition_aliases.append(f"{parent}.{part}")
    except Exception:
        pass
    report["catalog_rules"] = catalog_rules_for_composition(composition_aliases)

    manufacturer, item_type, found = _kind(item_id)
    report["manufacturer_en"] = manufacturer
    report["type_en"] = item_type
    if not found:
        report["error"] = f"unknown item id {item_id}"
        report["warnings"].append("item id is absent from lookup tables and dynamic kinds")
        return report

    try:
        display = resolver.resolve_item_display(item_id, manufacturer, item_type, canonical_decoded, lang) or {}
    except Exception as exc:
        display = {}
        report["warnings"].append(f"resolve_item_display failed: {type(exc).__name__}: {exc}")
    report["display"] = dict(display)
    report["display_name"] = str(display.get("display_name") or "")
    report["rarity"] = str(display.get("rarity") or "")
    report["display_source"] = str(display.get("display_source") or "")
    report["manufacturer"] = str(display.get("manufacturer") or manufacturer)
    report["type"] = str(display.get("item_type") or display.get("type") or item_type)

    if item_type in WEAPON_TYPES or item_type == HEAVY_TYPE:
        try:
            report["weapon_stats"] = resolver.resolve_weapon_stats(canonical_decoded) or {}
        except Exception as exc:
            report["warnings"].append(f"resolve_weapon_stats failed: {type(exc).__name__}: {exc}")
    # The save pipeline calls resolve_equipment_stats for every item type without
    # gating (core/bl4_functions.py:373), including Heavy Weapon, whose card is
    # built by equipment_card_html. Mirror that or heavy weapons lose their card.
    try:
        report["equipment_stats"] = resolver.resolve_equipment_stats(canonical_decoded, item_type) or {}
    except Exception as exc:
        report["warnings"].append(f"resolve_equipment_stats failed: {type(exc).__name__}: {exc}")

    rows = part_rows(canonical_decoded, item_id, item_type, lang)
    report["parts"] = rows
    counts = {"total": len(rows), "unknown": 0, "described": 0, "cosmetic": 0, "unmapped": 0}
    for row in rows:
        if not row["known"]:
            counts["unknown"] += 1
        counts[row["effect_state"]] = counts.get(row["effect_state"], 0) + 1
    report["part_counts"] = counts

    report["roundtrip"] = _roundtrip(decoded, base85)
    report["bit_layout"] = bit_layout(base85 or report["roundtrip"].get("encoded", ""))

    # Generation rules now cover every inventory root - shields, grenades,
    # repkits, heavy weapons, class mods and enhancements all ride the same
    # FInventoryTypeDef machinery - so validate whatever the index knows about
    # instead of gating on WEAPON_TYPES. `allow_incomplete` keeps an under-rolled
    # but otherwise lawful item out of the "modified" bucket.
    try:
        generation = resolver.validate_weapon_generation(canonical_decoded, allow_incomplete=True) or {}
        if generation.get("rules_available") and generation.get("weapon_known"):
            report["generation"] = generation
            subtype = _shield_subtype(generation) if item_type == "Shield" else ""
            report["equipment_subtype"] = subtype
            violations = list(generation.get("violations") or [])
            if subtype:
                violations = _annotate_shield_violations(violations, subtype)
            if _gold_skin_selected(item_id, item_type, rows):
                report["status"] = "gold"
                report["guidance_suppressed"] = "gold_skin"
                report["violations"] = []
            else:
                report["status"] = str(generation.get("status") or "")
                report["violations"] = violations
    except Exception as exc:
        report["warnings"].append(f"validate_weapon_generation failed: {type(exc).__name__}: {exc}")

    report["ok"] = True
    return report
