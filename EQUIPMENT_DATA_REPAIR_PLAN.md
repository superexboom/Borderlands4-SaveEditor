# Equipment Data / Legit Guidance Repair Plan

Status: completed
Started: 2026-08-08
Completed: 2026-08-08
Scope: Heavy Weapon, Grenade, Shield, Repkit, shared equipment firmware, update pipeline

## Execution contract

- Work continuously until implementation, integration, regression, commit, and push are complete.
- Do not pause for ordinary uncertainty, context compaction, failing tests, dependency setup, or recoverable implementation errors.
- Pause only when a missing game-side dump is the sole remaining blocker. If that happens, request the smallest exact dump set and provide capture instructions.
- Treat runtime dump `ITEM/SUMMARY/DISPLAY_TEXT` evidence as the regression oracle. Do not use probe output or the current implementation to generate its own expected values.
- Preserve user changes and the intentional Heavy Weapon T1 labels for the three untyped Torgue barrels.
- Firmware work is already consolidated into `Firmware/firmware.csv`; audit it, do not restore per-family firmware rows.
- Legit guidance is advisory: highlight legal choices and explain limits/dependencies, but never block modified combinations.
- The gold skin is a legendary-skin foundation with no natural composition. When selected, suppress natural-build guidance instead of reporting a nonexistent legal build.

## Confirmed baseline

### Heavy Weapon

- [x] Fix barrel picker name precedence: barrel base name before UIStat effect title; accessories remain UIStat-first.
- [x] Fix 12/244 ordinary names whose combined `axb/axd` barrel accessory loses the second canonical component.
- [x] Add missing catalog entries `273:37`, `273:38`, `273:39`, `273:41`.
- [x] Fix Loiter Sploiter damage/DPS/radius evaluation.
- [x] Fix Sea Eagle licensed-part projectile suppression.
- [x] Fix Jetsetter magazine override ordering.
- [x] Fix Flak Cannon explicit zero splash radius.
- [x] Reject pandas `NaN` labels and render no-effect parts as localized "No Stat Changes".

### Grenade

- [x] Add Transmitter `278:14/15` and its forced pairing.
- [x] Remove stale manufacturer-perk text once index/UIStat is authoritative.
- [x] Preserve the currently correct 82-item numeric regression.

### Shield

- [x] Correct `293:11` Collector body and `293:12` Collector legendary composition; remove historical Omega mapping.
- [x] Remove stale fixed `15% Resist` descriptions after dynamic output is covered.
- [x] Preserve the currently correct 80-item numeric regression.

### Repkit

- [x] Export/use the root manufacturer title part so ordinary names include Juicer/Tonic/Stim/etc.
- [x] Reproduce official prefix count/priority selection, including Borg multi-prefix names.
- [x] Hide mechanics carriers (including `243:66` and other `CARRIER_IDS`) from candidates; derive them internally.
- [x] Add missing Geiger-Roid element variants `243:115-118`.
- [x] Match game cooldown display rounding.
- [x] Fix resistance + immunity combined healing/cooldown/default inheritance.
- [x] Preserve both resistance and immunity in the Item Card element summary.

### Shared UIStat formatter

- [x] Honor `bDisplayAsPercentage`, `bDisplayPlusSign`, `bShowStatModifier`, reduction, and sign style.
- [x] Prevent DataTable values from being scaled twice.
- [x] Resolve isolated CritDamage/Damage/Cooldown/ProjectileSpeed modifiers.
- [x] Do not split internal hyphens in names.
- [x] Render or remove glyph tokens such as `action_gadget`.

### Firmware audit

- [x] Validate the 24 shared internal parts, localized names, L1-L3 descriptions, stack display, and owner-specific serial IDs.
- [x] Verify all four tabs, Item Card, Serial Inspector, PyInstaller resources, and Pipeline export read the shared table.
- [x] Confirm old per-family firmware rows cannot return on the next Pipeline run.

## Pipeline contract

- [x] Add a real `heavy/heavy_rarity.csv` target; never write rarity rows into the Heavy part CSV.
- [x] Dynamic part CSV files retain only structural catalog data (owner, ID, category, internal key where needed).
- [x] Full new NCS index is reconciled against all CSV rows every update; version diff is not the sole source of additions or reclassification.
- [x] Detect missing IDs, category drift, duplicate rows, stale dynamic descriptions, and exposed internal carriers.
- [x] Generate the shared firmware table automatically from current NCS/localization data.
- [x] Add deterministic Pipeline tests and preview assertions so cleaned schemas cannot silently expand again.

## Legit UI target

- [x] Show overall status: Legal / Incomplete / Modified, with one short reason summary.
- [x] Show each rule group's current count and legal min/max independently.
- [x] Highlight legal candidates with the theme accent color.
- [x] Keep nonmatching candidates selectable; show missing dependency, conflict, wrong slot, or full-slot reason.
- [x] Show forced parts and mechanics carriers as derived dependencies, not ordinary choices.
- [x] Split overloaded candidate pickers when one list cannot communicate the rule groups clearly, especially Shield primary/secondary and energy/armor/universal augments.
- [x] Suppress natural-build guidance for the gold skin.

## Regression gates

- [x] Heavy v4: 244 `verify=ok` blocks, exact name/rarity/core card values, including known special cases.
- [x] Grenade: 208 name samples and 82 numeric samples.
- [x] Shield: 214 name samples and 80 numeric samples.
- [x] Repkit: 396 runtime names plus 196 older legendary names; 395 trustworthy numeric samples match. One captured seed-3554 block is demonstrably torn and excluded.
- [x] Candidate descriptions contain no unresolved `{placeholder}`, accidental `?`, `nan`, internal glyph token, or stale CSV value.
- [x] CSV/index catalog closure passes for every selectable part and composition.
- [x] Existing unit, UI smoke, serialization/import-copy, Item Card, generation validator, and Pipeline tests pass.
- [x] Working tree contains no temporary regression artifacts.
- [x] Commit the completed repair and push `master` only after every locally verifiable gate passes.

## Final verification record

- `sav_edit`: 138 unit/UI tests passed; 214/214 Shield dump token round-trips passed after the missing-Model import fix.
- Runtime truth comparison: Heavy 244/244, Grenade names 208/208 and stats 82/82, Shield names 214/214 and stats 80/80, Repkit names 592/592 and trustworthy stats 395/395.
- Shared firmware: 24 rows, six owners × 24 mappings, 144 Card/Inspector/editor checks, no old per-family text source remains.
- Pipeline: 40/40 tests passed; full reconciliation and partial-firmware rejection are covered.
- PyInstaller: shared `Firmware/firmware.csv` is included by `pyinstaller_config.py`.

## Possible final game-side confirmation

Only request these if offline evidence cannot close the last verification:

- Heavy: Sidewinder and Heavy Turret.
- Grenade: Transmitter and uncovered `245:80/81` modifier examples.
- Repkit: non-corrosive Geiger-Roid variants.
