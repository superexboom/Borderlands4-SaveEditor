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
from typing import Any

from core import b_encoder, bl4_functions, decoder_logic, lookup
from core import item_display_resolver as resolver
from core import weapon_display_stats
from core.item_display_resolver import HEAVY_TYPE, WEAPON_TYPES

__all__ = ["inspect_serial", "part_rows", "bit_layout", "NO_STAT_TEXTS"]

# format_weapon_part_description returns this literal both for parts that truly
# have no stats and for parts whose payload cannot be rendered. Inspector output
# distinguishes the two by checking the ref payload directly.
NO_STAT_TEXTS = {"无属性变化", "No stat changes"}

# Exact strings produced by lookup.get_kind_enums / dynamic_item_kind. Heavy
# Weapon is included because its card and per-part stats go through the
# equipment path (see tabs.qt_items_tab.EQUIPMENT_CARD_FIELDS).
_EQUIPMENT_STAT_TYPES = {"Shield", "Grenade", "Repkit", "Enhancement", "Class Mod", HEAVY_TYPE}


def _blank(text: str) -> bool:
    return not text or not text.strip()


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


def _kind(item_id: int) -> tuple[str, str, bool]:
    manufacturer, item_type, found = lookup.get_kind_enums(item_id)
    if found:
        return manufacturer, item_type, True
    dynamic = resolver.dynamic_item_kind(item_id)
    if dynamic:
        return dynamic[0], dynamic[1], True
    return "", "", False


def _ref_payload(ref: dict[str, Any]) -> int:
    return (
        len(ref.get("weapon_stat_modifiers") or [])
        + len(ref.get("weapon_attribute_effects") or [])
        + len(ref.get("uistats") or [])
    )


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
    is_weapon = item_type in WEAPON_TYPES or item_type == HEAVY_TYPE
    rows: list[dict[str, Any]] = []
    for key in keys:
        owner, _, part_id = key.partition(":")
        ref = refs.get(key) or {}
        names = ref.get("name") or {}
        category = str(ref.get("category") or "")
        payload = _ref_payload(ref)

        description = ""
        if is_weapon:
            try:
                description = (
                    resolver.format_weapon_part_description(int(owner), part_id, decoded_full, lang, category) or ""
                ).strip()
            except Exception:
                description = ""
        # Heavy Weapon counts as a weapon for naming but is driven by the
        # equipment tables, so fall through when the weapon formatter says nothing.
        if _blank(description) or description in NO_STAT_TEXTS:
            if item_type in _EQUIPMENT_STAT_TYPES:
                # Equipment parts have never had a per-part breakdown in the UI;
                # this helper already does the leave-one-out delta.
                try:
                    equipment_text = (
                        resolver.format_equipment_part_description(
                            decoded_full, item_type, key, lang, strict_delta=True
                        )
                        or ""
                    ).strip()
                except Exception:
                    equipment_text = ""
                if equipment_text:
                    description = equipment_text

        if description in NO_STAT_TEXTS or _blank(description):
            # Separate "genuinely cosmetic" from "payload present but unmapped".
            effect_state = "unmapped" if payload else "cosmetic"
        else:
            effect_state = "described"

        display_name = ""
        try:
            display_name = resolver.weapon_part_name(int(owner), part_id, lang) or ""
        except Exception:
            display_name = ""
        if _blank(display_name):
            display_name = str(
                names.get("zh" if resolver._lang_is_zh(lang) else "en") or names.get("en") or ""
            ).strip()

        rows.append(
            {
                "key": key,
                "owner": owner,
                "part_id": part_id,
                "known": bool(ref),
                "category": category,
                "part": str(ref.get("part") or ""),
                "rarity": str(ref.get("rarity") or ""),
                "name": display_name,
                "name_en": str(names.get("en") or ""),
                "name_zh": str(names.get("zh") or ""),
                "description": description,
                "effect_state": effect_state,
                "payload_count": payload,
                "uistats": list(ref.get("uistats") or []),
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
        "decoded_parts": "",
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
        "violations": [],
        "warnings": [],
    }

    decoded, base85, error = _decode_any(text)
    report["base85"] = base85
    report["decoded_full"] = decoded
    if error or _blank(decoded):
        report["error"] = error or "could not decode input"
        return report

    header = bl4_functions.parse_decoded_item_header(decoded)
    if not header:
        report["error"] = "header parse failed"
        return report

    item_id = header["mfg_id"]
    report["item_id"] = item_id
    report["level"] = header.get("level")
    report["seed"] = header.get("seed")
    report["implicit_level_one"] = bool(header.get("implicit_level_one"))
    report["decoded_parts"] = str(header.get("component") or "").strip()

    manufacturer, item_type, found = _kind(item_id)
    report["manufacturer_en"] = manufacturer
    report["type_en"] = item_type
    if not found:
        report["error"] = f"unknown item id {item_id}"
        report["warnings"].append("item id is absent from lookup tables and dynamic kinds")
        return report

    try:
        display = resolver.resolve_item_display(item_id, manufacturer, item_type, decoded, lang) or {}
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
            report["weapon_stats"] = resolver.resolve_weapon_stats(decoded) or {}
        except Exception as exc:
            report["warnings"].append(f"resolve_weapon_stats failed: {type(exc).__name__}: {exc}")
    # The save pipeline calls resolve_equipment_stats for every item type without
    # gating (core/bl4_functions.py:373), including Heavy Weapon, whose card is
    # built by equipment_card_html. Mirror that or heavy weapons lose their card.
    try:
        report["equipment_stats"] = resolver.resolve_equipment_stats(decoded, item_type) or {}
    except Exception as exc:
        report["warnings"].append(f"resolve_equipment_stats failed: {type(exc).__name__}: {exc}")

    rows = part_rows(decoded, item_id, item_type, lang)
    report["parts"] = rows
    counts = {"total": len(rows), "unknown": 0, "described": 0, "cosmetic": 0, "unmapped": 0}
    for row in rows:
        if not row["known"]:
            counts["unknown"] += 1
        counts[row["effect_state"]] = counts.get(row["effect_state"], 0) + 1
    report["part_counts"] = counts

    report["roundtrip"] = _roundtrip(decoded, base85)
    report["bit_layout"] = bit_layout(base85 or report["roundtrip"].get("encoded", ""))

    if item_type in WEAPON_TYPES:
        # validate_weapon_generation returns weapon_generation_context plus
        # "status" and "violations", so one call covers both.
        try:
            generation = resolver.validate_weapon_generation(decoded) or {}
            report["generation"] = generation
            report["status"] = str(generation.get("status") or "")
            report["violations"] = list(generation.get("violations") or [])
        except Exception as exc:
            report["warnings"].append(f"validate_weapon_generation failed: {type(exc).__name__}: {exc}")

    report["ok"] = True
    return report
