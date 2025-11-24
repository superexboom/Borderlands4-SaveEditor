# -*- coding: utf-8 -*-
"""
This module is a direct port of the 'lookup.go' file.
It provides mappings and lookup functions for item IDs, types, and manufacturers.
"""

# English constants for manufacturers and item types
Jakobs = "Jakobs"
Tediore = "Tediore"
Torgue = "Torgue"
Maliwan = "Maliwan"
Daedalus = "Daedalus"
Vladof = "Vladof"
Order = "Order"
Ripper = "Ripper"
CoV = "CoV"
Hyperion = "Hyperion"
Atlas = "Atlas"
Vex = "Vex"
Amon = "Amon"
Rafa = "Rafa"
Harlowe = "Harlowe"

Pistol = "Pistol"
Shotgun = "Shotgun"
SMG = "SMG"
SniperRifle = "Sniper"
AssaultRifle = "Assault Rifle"
HeavyWeapon = "Heavy Weapon"
Grenade = "Grenade"
Shield = "Shield"
Repkit = "Repkit"
ClassMod = "Class Mod"
Enhancement = "Enhancement"

# ID_MAP using English constants
ID_MAP = {
    (Daedalus, Pistol): 2,
    (Jakobs, Pistol): 3,
    (Order, Pistol): 4,
    (Tediore, Pistol): 5,
    (Torgue, Pistol): 6,
    (Ripper, Shotgun): 7,
    (Daedalus, Shotgun): 8,
    (Jakobs, Shotgun): 9,
    (Maliwan, Shotgun): 10,
    (Tediore, Shotgun): 11,
    (Torgue, Shotgun): 12,
    (Daedalus, AssaultRifle): 13,
    (Tediore, AssaultRifle): 14,
    (Order, AssaultRifle): 15,
    (Vladof, SniperRifle): 16,
    (Torgue, AssaultRifle): 17,
    (Vladof, AssaultRifle): 18,
    (Ripper, SMG): 19,
    (Daedalus, SMG): 20,
    (Maliwan, SMG): 21,
    (Vladof, SMG): 22,
    (Ripper, SniperRifle): 23,
    (Jakobs, SniperRifle): 24,
    (Maliwan, SniperRifle): 25,
    (Order, SniperRifle): 26,
    (Jakobs, AssaultRifle): 27,
    (Rafa, ClassMod): 254,
    (Amon, ClassMod): 255,
    (Vex, ClassMod): 256,
    (Harlowe, ClassMod): 259,
    (Torgue, Repkit): 261,
    (Maliwan, Grenade): 263,
    (Hyperion, Enhancement): 264,
    (Jakobs, Repkit): 265,
    (Maliwan, Repkit): 266,
    (Jakobs, Grenade): 267,
    (Jakobs, Enhancement): 268,
    (Vladof, Repkit): 269,
    (Daedalus, Grenade): 270,
    (Maliwan, Enhancement): 271,
    (Order, Grenade): 272,
    (Torgue, HeavyWeapon): 273,
    (Ripper, HeavyWeapon): 275,
    (Ripper, Repkit): 274,
    (Daedalus, Repkit): 277,
    (Ripper, Grenade): 278,
    (Maliwan, Shield): 279,
    (Order, Enhancement): 281,
    (Vladof, HeavyWeapon): 282,
    (Vladof, Shield): 283,
    (Atlas, Enhancement): 284,
    (Order, Repkit): 285,
    (CoV, Enhancement): 286,
    (Tediore, Shield): 287,
    (Maliwan, HeavyWeapon): 289,
    (Tediore, Repkit): 290,
    (Vladof, Grenade): 291,
    (Tediore, Enhancement): 292,
    (Order, Shield): 293,
    (Ripper, Enhancement): 296,
    (Torgue, Grenade): 298,
    (Daedalus, Enhancement): 299,
    (Ripper, Shield): 300,
    (Torgue, Enhancement): 303,
    (Jakobs, Shield): 306,
    (Vladof, Enhancement): 310,
    (Tediore, Grenade): 311,
    (Daedalus, Shield): 312,
    (Torgue, Shield): 321,
}

REVERSE_ID_MAP = {v: k for k, v in ID_MAP.items()}

def get_item_type_id(manufacturer: str, item_type: str) -> (int, bool):
    """
    Looks up the ID for a (Manufacturer/Character, ItemType) combination.
    Returns the ID and a boolean indicating if it was found.
    """
    return ID_MAP.get((manufacturer, item_type), (0, False))

def get_kind_enums(item_id: int) -> (str, str, bool):
    """
    Looks up the (Manufacturer/Character, ItemType) for a given ID.
    Returns (manufacturer, item_type, found_boolean).
    """
    if item_id in REVERSE_ID_MAP:
        manufacturer, item_type = REVERSE_ID_MAP[item_id]
        return manufacturer, item_type, True
    return "Unknown", "Unknown", False
