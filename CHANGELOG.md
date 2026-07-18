# Changelog

Changes on top of upstream v3.6.1 (`origin/master`). Grouped by theme; each
bullet is one or more commits. RU/UA translations are best-effort and listed
for native review in `TRANSLATION_REVIEW.md`.

## Bug fixes

- **Fix crash when pasting a serial into the Base85 field.** `handle_b85_change`
  called `bl4f.decode_serial_to_string`, but that function lives in
  `decoder_logic` — with the field focused (i.e. a user pasting a serial to
  edit it), it raised `AttributeError`. Now calls `decoder_logic`. *(Long-
  standing; present since the weapon-editor file's first commit.)*
- **Fix move-part up/down buttons needing multiple clicks per move.**
  `parts_data` interleaves whitespace separators with part dicts; `move_part`
  stepped the raw index by ±1, so every other click swapped a separator and
  moved nothing. Now steps over separators to the adjacent real part. One
  click = one move.
- **Fix invisible soft hyphen (U+00AD) breaking RU/UA container lookup.** The
  Chinese alias key `"装备中­"` in the RU/UA files carried a stray soft hyphen,
  so those users saw raw `装备中` instead of the localized "Equipped".
- **Gate Save / Save As on a loaded save**, not the current tab index — the nav
  bar could light up the actions before any save was open.

## Localization (four languages: zh-CN, en-US, ru, ua)

The app shipped four languages but many strings were hardcoded as
`"中文" if zh-CN else "English"` two-language conditionals, so **Russian and
Ukrainian users saw English** throughout. Routed them through the JSON:

- **Weapon editor** — search placeholder, part tooltips, element/licensed group
  titles, the selected-weapon summary, the Add-Part catalog picker, and the
  narrow-card stat headers, all localized (new `tooltips`/`parts`/`summary`/
  `catalog`/`stat_short` key groups).
- **Class mod & enhancement** — perk-filter labels, skill-tree colours, the
  stack/stat picker chrome, and the enhancement category/subcategory taxonomies
  now carry all four languages.
- **Flag labels** centralized into one `resource_loader.get_flag_labels()`
  helper, replacing seven copy-pasted bilingual maps across the editor tabs.
- **Encode-error prefix** localized (`dialogs.error`) and the fragile
  error-text sniffing it relied on replaced with an explicit state flag.
- **Loadout** item-name decode fallbacks and the **Lost Loot** container ID
  normalized/localized.

Author-facing text left as-is on purpose: Chinese debug logs and core
diagnostics (this is a zh-default project), and English crypto/dependency
errors (technical, universal).

## Weapon-editor UI

- **Backpack moved to a left column of vertical rarity cards** (from full-width
  rows): a custom-painted rarity plate with the weapon-type icon punched
  through it so the gun reads in its tier colour, a per-tier border, and a
  tight-banded Pearl gradient phased so Pearl reads teal (not gold like
  Legendary). Draggable splitter between column and editor.

## Windows / packaging

- **Force UTF-8 stdio at startup** so a frozen Windows build doesn't crash on
  the app's Chinese log prints (cp1252 can't encode them).

## Code hygiene

- Derive the all-tabs language-sync list from the content stack (one source of
  truth instead of two hand-maintained literals).
- Drag the frameless window via `QWindow.startSystemMove()` (smooth under
  Wayland) instead of manual geometry tracking.
- Theme the non-native `QFileDialog` and generic `QListView` (were see-through
  on the frosted-glass background).
- Remove unused/redundant imports flagged by pyflakes.
