# SaveEditor optimization and QML preview

Approved implementation checklist, based on master `970ee43` (4.1.1).
Keep the Python core, save/Live formats and existing data update pipeline.
Deliver an optimized editor candidate and a separate, read-only QML preview.

## 1. Batch work and YAML

- [x] Queue controller dirty notifications onto the GUI thread.
- [x] Remove fixed per-item sleeps; report progress at most every 50 ms, plus start/end.
- [x] Add a locked bulk-backpack operation with one slot scan and combined dirty notification.
- [x] Iterate combinations without an intermediate combination list.
- [x] Share safe YAML loading/dumping, preferring LibYAML with a Python fallback.
- [x] Verify save round trips, batch counts/slots and GUI-thread notifications (25 tests, 2 subtests).

## 2. Lists

- [ ] Reuse inventory model rows during filtering; cache searchable text and preserve selection/group state.
- [ ] Debounce text search by 100 ms; apply other filters immediately.
- [ ] Reuse inline catalog row widgets, updating visibility/counts only.
- [ ] Preserve hover-card cache across searches; invalidate when display inputs change.
- [ ] Compare 5,000 inventory rows and 800 catalog rows against the recorded baseline.

## 3. Cleanup and shared presentation

- [ ] Delete the unused loadout weapon CSV/localization loaders and unreachable duplicate code.
- [ ] Share localized labels, units and errors through existing language resources.
- [ ] Move card presentation out of the inventory tab; retain one implementation for hover and export.
- [ ] Cache background blur and size/DPI-dependent scaling.
- [ ] Record dependency versions and track a small core regression set; ignore local QA artifacts.

## 4. QML preview

- [ ] Independent PyQt6 QQmlApplicationEngine/QQuickWindow and QAbstractListModel.
- [ ] Existing game assets and resolved sample data; default 200 rows and optional 5,000-row stress data.
- [ ] Search, facets, grouping, selection, hover cards and collapsible navigation.
- [ ] Game-inspired dense layout, dark/light themes, four languages, custom background.
- [ ] Short navigation/selection/card/filter animations and an animation-off setting.
- [ ] Validate 1600x900, narrow layouts and 100/150/200% scale, then real Windows rendering.
- [ ] Build and smoke a separate self-contained QML preview EXE.

## 5. Delivery

- [ ] Run focused correctness/Live-identity regressions and record median/P95 performance.
- [ ] Build and smoke the optimized editor candidate without replacing previous release artifacts.
- [ ] Record startup/memory/package size and real-renderer animation measurements.
- [ ] Commit each validated stage and record candidate artifacts and remaining validation limits.

## Baseline (2026-09-09, local diagnostic samples)

| Workload | Baseline |
| --- | ---: |
| 200 valid conversions | 2.099 s |
| 5,000 inventory rows, search preserving all matches | 179.33 ms median |
| 800 inline catalog rows, search preserving all matches | 380.98 ms median |
| 319,899-byte YAML, load / dump | 162.2 / 115.3 ms median |
| 4,000 in-memory backpack additions | 912.2 ms |
| 1600x900 offscreen resize and capture with background blur | 12.8 ms median |

The baseline uses synthetic/repeated valid items and offscreen widgets; it is
not an animation frame-rate measurement. The update is expected around
2026-09-11 00:00 China time; UI work and reviewed data imports remain independent.
