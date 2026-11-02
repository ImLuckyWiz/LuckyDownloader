# LuckyDownloader Migration Handoff & Progress

## 1. Baseline Test Suite

- **Date:** 2026-11-02
- **Command:** `pytest`
- **Result:** 1,682 passed, 31 skipped, 1 warning (126.96s)
- **Environment:** Windows (win32), Python 3.14.7, PySide6 6.12.0
- **Rule:** Subsequent phases must maintain all tests passing. The skipped count (31) must not grow without an explicit written reason.

## 2. Working Rules

1. **One phase at a time:** Focus solely on the active phase deliverables.
2. **Tests must be green:** The full test suite must pass before any phase is marked `done`.
3. **Phase 1 refactor must not change behavior:** Moving logic to `core/providers/` is purely architectural; existing Twitch features and test outcomes must remain identical.
4. **Update HANDOFF.md:** Update status and one-line summaries in this document at the conclusion of each phase.
5. **Stop and report when blocked:** Report issues or blockers immediately instead of making unverified assumptions.

## 3. Phase Checklist

| Phase | Description | Status | Note |
|---|---|---|---|
| **Phase 0** | Safety net and transitional release (updater dual-repo/asset support) | done | Updater accepts both LuckyTwitch and LuckyDownloader repo prefixes and asset names (1,594 passed). |
| **Phase 1** | Provider layer (`core/providers/`, neutral source/job contracts) | done | Introduced Provider ABC, Capability flags, TwitchProvider, GenericProvider, detect_source, neutral SourceInfo & finalize guards (1,637 passed, 31 skipped). |
| **Phase 2** | Generic source info and format selection (`generic.py`, yt-dlp spikes & fixtures) | done | Offline parsing for YouTube/TikTok/IG/Reddit fixtures, format selection, args builder, naming templates & playlist rejection (1,665 passed, 31 skipped). |
| **Phase 3** | Generic download flow in the UI (adaptive Plan tab card, Queue, History) | done | Simple card mode for non-timeline sources, async thumbnail loader, 7-column History with site & URL support, Queue delegate fallback thumb, full video enqueueing (1,672 passed, 31 skipped). |
| **Phase 4** | Reliability for YouTube, TikTok, and Instagram (error mapping, cookies, runtimes) | done | Cookies from browser option in Settings/Tools & job options, mapped errors with suggested actions (login, age, geoblock, rate limit, extractor), extractor update & retry prompt, yt-dlp generic format selector fix verified live with YouTube (1,680 passed, 31 skipped). |
| **Phase 5** | Rebrand and Release 1 (repo/folder rename handoff, branding assets, link scheme) | done | Git remote updated to LuckyDownloader; updater release API updated; per-user first-run non-destructive migration from LuckyTwitch; dual URL schemes (luckydownloader:// default + luckytwitch:// alias); Premiere CEP plugin dual format support; gettext domain renamed to luckydownloader (i18n check clean); installer & build scripts updated with AppId retention; UI branding & docs rebranded (1,682 passed, 31 skipped; 134 CEP tests passed). |
| **Phase 6** | Playlists and channels (Release 2) | done | Flat playlist/channel extraction (-J --flat-playlist), PlaylistPickerDialog with range parser, select all/none, async entry thumbnails & YouTube fallback, --download-archive skip support, large item confirmation, Queue clear queue action, multi-selection & async thumbnail fetch (1,716 passed, 31 skipped). |
| **Phase 6b** | Provider folders and download routing (Release 2) | done | Provider folder routing, provider_subfolders switch, custom provider_out_dirs overrides, {site}/{provider} naming & folder tokens, Plan tab & Playlist dialog pre-population (1,731 passed, 31 skipped). |
| **Phase 7** | Browse tab with provider selector (Release 3) | done | Renamed Search to Browse (rail, TAB_NAMES, ES i18n), added YouTubeProvider with ytsearch & channel listing, provider selector at top of Browse tab (shown when >1 browsable provider), backward-compat aliases for SearchTab & tab_search, separate recent searches, bilingual translations (1,739 passed, 31 skipped). |
| **Phase 8** | Subscriptions & watchlist multi-provider | done | Generalized WatchedChannel/WatchedStreamer with multi-provider and URL support, YouTube flat channel checks, backward-compatible Twitch format support, BrowseTab pin button integration for YouTube channels, bilingual ES i18n (1,742 passed, 31 skipped). |
| **Phase 9** | Cut editor for generic sources & internal cleanups | done | Cut editor support for generic/non-timeline sources (yt-dlp section downloads, chapters & storyboard parsing, optional cuts input, part cards & preview, multi-part queueing, browser cookies forwarding), modern facade modules `luckydownloader_engine.py` & `luckydownloader_qt.py`, bilingual ES i18n verified (1,745 passed, 31 skipped). |
