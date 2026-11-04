# Documentation Index

This directory contains specifications, architectural plans, and upgrade roadmaps for LuckyDownloader and its Premiere Pro integration.

## Primary Entry Points & Architecture
- **Desktop Application (PySide6 / Qt):** [`luckydownloader_qt.py`](../luckydownloader_qt.py) (legacy facade: [`luckytwitch_qt.py`](../luckytwitch_qt.py))
- **Engine Core:** [`luckydownloader_engine.py`](../luckydownloader_engine.py) / [`core/`](../core/)
- **Provider System:** [`core/providers/`](../core/providers/)
- **Premiere Pro CEP Panel:** [`premiere-plugin-cep/`](../premiere-plugin-cep/)
- **Comprehensive Project Review:** [`REVIEW_2026_11.md`](REVIEW_2026_11.md)

---

## Documents & Roadmaps

| Document | Type | Status | Description |
|---|---|---|---|
| [`PLAN_00_MASTER_INDEX.md`](PLAN_00_MASTER_INDEX.md) | Master Plan | Active | Master execution index and progress tracker across 7 release phases. |
| [`REVIEW_2026_11.md`](REVIEW_2026_11.md) | Audit & Review | Active | Comprehensive 2026 codebase audit covering pipeline, UI, security, and tests. |
| [`link-format.md`](link-format.md) | Specification | Active (v1) | URL scheme contract for `luckydownloader://open` and `luckytwitch://open` deep links. |
| [`markers-format.md`](markers-format.md) | Specification | Active (v1) | JSON marker exchange format contract between the app and the Premiere CEP panel. |
| [`i18n-glossary-es.md`](i18n-glossary-es.md) | Style guide | Active | Spanish style rules and glossary; enforced by `python tools/i18n.py check`. |
| [`ANIMATIONS_UPGRADE_PLAN.md`](ANIMATIONS_UPGRADE_PLAN.md) | Plan | Done in v2.1.0 | 60 FPS motion system, micro-interactions, tokens, and reduced-motion compliance. |
| [`ENGINE_SPLIT_MAP.md`](ENGINE_SPLIT_MAP.md) | Blueprint | Done in v2.5.0 | Complete symbol and dependency map for modularizing luckytwitch_engine.py into core/. |
| [`FIRST_RUN_WELCOME_PLAN.md`](FIRST_RUN_WELCOME_PLAN.md) | Plan | Done in v2.1.0 | First-run welcome overlay and quick setup experience. |
| [`LINUX_BUILD_PLAN.md`](LINUX_BUILD_PLAN.md) | Plan | Done in v2.4.0 | Native Linux packaging plan (AppImage and tarball for x86_64). |
| [`NAMING_TOKENS_EXPANSION_PLAN.md`](NAMING_TOKENS_EXPANSION_PLAN.md) | Plan | Done in v2.2.1 | Output file and stream folder naming template tokens expansion. |
| [`NEW_WINDOW_BAR.md`](NEW_WINDOW_BAR.md) | Plan | Done in v2.6.0 | Custom window bar (title bar drawn by the app) keeping native snap, shadow and resize on Windows; optional integrated command bar; Linux and macOS follow-ups. |
| [`fixwindowbar.md`](fixwindowbar.md) | Fix Plan | Done in v2.6.1 | Native Win32 window resizing borders, DWM shadow extension, and Snap Layouts menu on maximize button. |
| [`WINDOW_BAR_FIX_2_6_2.md`](WINDOW_BAR_FIX_2_6_2.md) | Fix Plan | Done in v2.6.2 | Fix un-maximize by dragging caption, calculate_client_rect pure logic, and repair frameless_spike.py tool. |
| [`NEXT_UPGRADES_PLAN.md`](NEXT_UPGRADES_PLAN.md) | Plan | Done in v2.9.0 | Master roadmap: Housekeeping (v2.3.1), Linux (v2.4.0), Engine split (v2.5.0), Window bar (v2.6.0), Premiere panel (v0.15.0), and App Features F1-F4 (v2.9.0). |
| [`QUALITY_AND_AUDIO_PLAN.md`](QUALITY_AND_AUDIO_PLAN.md) | Plan | Done in v2.2.0 | Stream quality picker and lossless / converted audio extraction (.m4a / .mp3). |
| [`TITLE_CLEANING_AND_NAMING_PLAN.md`](TITLE_CLEANING_AND_NAMING_PLAN.md) | Plan | Done in v2.1.1 | Bot command stripping, title editing in Plan tab, and single-part naming cleanup. |
| [`UPDATE_DETECTION_PLAN.md`](UPDATE_DETECTION_PLAN.md) | Plan | Done in v2.3.0 | Automated GitHub update detection, update dialog, and Windows silent in-place updater. |
| [`VERIFICATION_CHECKLIST.md`](VERIFICATION_CHECKLIST.md) | Checklist | In progress | Real-hardware verification matrix across Windows, macOS, and Adobe Premiere Pro (Phase V). |
| [`I18N_SPANISH_PLAN.md`](I18N_SPANISH_PLAN.md) | Plan | In progress (I0 done) | Finish and harden the Spanish localization (coverage, live switching, engine messages, installer, panel). |
| [`PROJECT_AUDIT_2026_10.md`](PROJECT_AUDIT_2026_10.md) | Audit + Plan | Pending | Full project audit of v2.9.0 with findings and a remediation plan (R1 to R5). |
| [`UPGRADE_REVIEW_2026_10.md`](UPGRADE_REVIEW_2026_10.md) | Review + Plan | Pending | Progress review of the upgrade plan, what was missed, and new feature ideas. |
