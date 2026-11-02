# LuckyDownloader: Phase Plan

From LuckyTwitchDownloader to a multi-site downloader (YouTube, TikTok, Instagram and anything yt-dlp supports), keeping the Twitch VOD workflow intact.

## 1. Decisions locked

- **Name:** LuckyDownloader. The repo name and the `luckydownloader://` link scheme were checked and are free.
- **Rename in place:** the GitHub repo is renamed (no new repo). A transitional release goes out first so installed copies can still update.
- **Link-first:** the top-bar link field is the universal entry. Any pasted URL is routed by site.
- **Providers:** Twitch is the first provider. A generic yt-dlp provider handles every other site.
- **Adaptive Plan tab:** full timeline for Twitch VODs, a simple card for ordinary videos, an item picker for playlists and channels.
- **Search becomes Browse**, with a provider selector that lists only providers that can browse. No provider-grid Home page.
- **Out of Release 1:** YouTube search and channel browsing, and the cut editor for non-Twitch sites.
- **Twitch sign-in stays optional:** it is only needed for Twitch Browse and Twitch-only features.

## 2. Releases

- **Release 1 (first LuckyDownloader):** phases 0 to 5. Paste a link from any site yt-dlp supports and download it. Twitch works as before.
- **Release 2:** playlists and channels (phase 6).
- **Release 3:** Browse and subscriptions (phases 7 and 8).
- **Later:** phase 9.

## 3. Working rules

- Follow the rules in HANDOFF.md: one phase at a time, test suite must be green before counting a phase as done, phase 1 refactor must not change behavior, update HANDOFF.md at the end of each phase, and stop and report when blocked.
- Every phase ends with the full test suite green. The refactor in phase 1 must not change behavior.
- Every new UI string goes through the i18n helpers, and the English and Spanish catalogs are updated in the same phase.
- A phase is finished only when every item under its Done when heading is true.

## 4. Target architecture

A new package `core/providers/`:

- `base.py`: the `Provider` interface and the capability flags.
- `twitch.py`: wraps what exists today (Twitch client, VOD lookup, game segments, storyboards, muted ranges, clips).
- `generic.py`: the fallback that uses `yt-dlp -J` for any other URL.
- `detect.py`: `detect_source(url)` returns the provider and a cleaned URL. Twitch is tried first and generic last. Bare Twitch VOD IDs and streamer names keep working as they do now.

Capability flags, which the UI reads instead of provider names: `RESOLVE`, `SEGMENTS`, `TIMELINE`, `CHAT`, `BROWSE`, `SUBSCRIBE`, `PLAYLIST`.

A provider-neutral source record holds id, title, uploader, duration, thumbnail, site and formats. Twitch-only fields (`twitch_vod_id`, game segments, storyboard, muted ranges) stay optional on the Twitch variant.

## Phase 0: Safety net and transitional release

**Goal:** make the later rename safe for people who already have the app.

**Work**

- Run the full suite on Windows and record the baseline (number of tests passing) and phase checklist in HANDOFF.md.
- In `core/updates.py`, make `is_safe_asset_url` accept the download prefixes of both repo names (`LuckyTwitchDownloader` and `LuckyDownloader`).
- Make `pick_asset` match release files named either `LuckyTwitch-*` or `LuckyDownloader-*`.
- Extend `tests/test_updates.py` to cover both names.
- Ship it as a normal release and give people time to update before the rename in phase 5.

**Done when**

- The baseline test count is recorded.
- The updater accepts both repo prefixes and both asset name patterns, with tests.
- The transitional release is published.

## Phase 1: Provider layer (no visible change)

**Goal:** separate Twitch-specific logic from the generic pipeline without changing behavior.

**Work**

- Create `core/providers/` with the interface, the capability flags, the Twitch provider and `detect_source`.
- Make `core/job.py` stop importing `TwitchClient` directly. The client becomes optional and is created only for Twitch jobs.
- In `core/finalize.py`, replace direct reads of `twitch_vod_id` with the provider-neutral `id`, and guard the clips, chat and muted-range steps by capability.
- Keep the existing `luckytwitch_engine` facade working as it is.

**Tests**

- New `tests/test_providers.py`: `detect_source` for Twitch URLs (VOD, clip, channel), bare VOD IDs, YouTube, TikTok, Instagram, Reddit and invalid text.
- All existing tests pass unchanged.

**Done when**

- The existing suite is green.
- A Twitch job runs with no code path that needs a signed-in client unless it uses a Twitch-only feature.

## Phase 2: Generic source info and format selection

**Goal:** resolve any yt-dlp URL into a source record and decide what to download.

**Work**

- Do the spikes in section 5 first, and save real sample outputs as fixtures.
- `core/providers/generic.py`: run `yt-dlp -J --no-playlist` through the managed yt-dlp from `core/tools.py` and build the neutral source record. Detect playlists and channels and report them as such (the picker comes in phase 6).
- Generalize `VideoFormat` and the quality list in `core/source_info.py`, which today describe what Twitch offers: height, fps, audio only, container and size when known.
- Build the yt-dlp format string from the choice (best, a maximum height, audio only) and the container (MP4, MKV, MP3, M4A). The existing audio-only code in `core/download.py` is the starting point.
- Add a naming template for non-Twitch jobs (uploader, date, title, id) using the existing `safe_name` and auto-clean rules.

**Tests**

- Fixtures under `tests/fixtures/` with trimmed yt-dlp JSON for YouTube, TikTok, Instagram and Reddit.
- Offline tests for parsing, quality lists and format strings.

**Done when**

- From a fixture alone, the code returns a correct source record, quality list and yt-dlp arguments, offline.

## Phase 3: Generic download flow in the UI

**Goal:** paste any link and download it.

**Work**

- Route the top-bar link field through `detect_source`. Twitch keeps going to the Plan tab as it does now, and anything else shows the simple card.
- Plan tab card mode: thumbnail, title, uploader, duration, quality dropdown, audio-only toggle, container, output folder and Add to queue. The timeline, cut text box and game bars are hidden unless the provider has `TIMELINE`.
- Queue, History and the Downloaded badge accept non-Twitch jobs (a site column and generic naming).
- Empty and error states with friendly messages: unsupported URL, private video, network error.

**Tests**

- New `tests/test_qt_generic_plan.py` in the style of the existing Qt tests.
- Update `test_qt_main_window.py`, `test_qt_queue_tab.py` and `test_history.py`.

**Done when**

- On Windows, a YouTube link and a TikTok link can be pasted, shown in the card, queued, downloaded and found in History.
- A Twitch VOD still behaves exactly as before.

## Phase 4: Reliability for YouTube, TikTok and Instagram

**Goal:** the common failures have a clear path instead of a raw yt-dlp error.

**Work**

- Check whether the current yt-dlp needs an external JavaScript runtime for YouTube. If it does, add the runtime to the managed tools in `core/tools.py` (download, checksum check, shown in `describe_tools`), the same way yt-dlp and ffmpeg are handled.
- Add an Options setting for cookies from the browser (`--cookies-from-browser`), with a short explanation of when it helps: age-restricted or login-required content and some TikTok and Instagram links.
- Map the common yt-dlp errors (login required, age-restricted, geo-blocked, private, unsupported URL, rate limited) to short translated messages with a suggested action.
- Keep the yt-dlp auto-update, and add a Retry after updating yt-dlp action for extractor failures.

**Tests**

- Error-mapping unit tests from saved error text samples.
- Tool-install tests in the style of the existing ones.

**Done when**

- Each mapped error shows its message.
- The cookies option works on a site that needs it.
- A clean install can download from YouTube with no manual steps.

## Phase 5: Rebrand and Release 1

**Goal:** ship LuckyDownloader without breaking existing users.

**Visible changes**

- Rename the GitHub repo (only after the transitional release has had time to spread), then run `git remote set-url` locally.
- Update the updater constants in `core/updates.py` (the API, release page and download prefix URLs).
- Rename the app in the window title, welcome overlay, README.md, README.es.md and RELEASE\_NOTES.md.
- Rename the release files (`LuckyDownloader-Setup.exe`, the macOS dmg, the AppImage and the tar.gz) in `build_mac.sh`, `build_linux.sh`, `installer.iss` and `.github/workflows/build.yml`, and the assets `luckytwitch.desktop` and `luckytwitch.png`.
- Link scheme: register `luckydownloader://` and keep `luckytwitch://` as a legacy alias in `weblink.py`, so existing links and the Premiere panel keep working. Update `docs/link-format.md`.
- Update the Premiere plugin name and links, keeping it compatible with both schemes.
- Rename the gettext files (`locale/luckytwitch.pot`, the Spanish `.po` and `.mo`) and the scripts in `tools/i18n.py`.

**Data and installs**

- On first run, migrate (copy, never delete) settings, history, watch list, recent streamers and the managed tools from the old data folder to the new one, so nobody starts empty. Check `core/paths.py` for the exact folders.
- Windows installer: keep the same Inno Setup `AppId` so the new installer upgrades the old install instead of installing next to it. Check the old Start menu and uninstall entries.
- macOS: decide whether to keep the bundle identifier. Changing it makes macOS treat the app as a different one.
- Linux: new `.desktop` file and icon names.

**Internal names (can wait)**

- `luckytwitch_engine.py` and `luckytwitch_qt.py` can keep their names for Release 1. `core/download.py` and `core/finalize.py` look up `luckytwitch_engine` through `sys.modules`, and tests replace functions through it, so renaming means changing every lookup in one mechanical commit. Leave that for phase 9.

**Tests**

- Adjust `test_weblink.py`, `test_updates.py` and `test_ui_language.py`.
- Add a test for the data-folder migration.

**Done when**

- A copy of the transitional release updates itself to LuckyDownloader on Windows.
- Old `luckytwitch://` links still open the app, and `luckydownloader://` links work too.
- Settings and history survive the update.
- All release assets build in the workflow with the new names.

## Phase 6: Playlists and channels (Release 2)

**Goal:** download many items from one link.

**Work**

- Detect playlists and channels and fetch the item list with flat extraction (`--flat-playlist -J`).
- Picker dialog: rows with thumbnail, title and duration, select all and none, and a range selector.
- Queue one job per picked item with shared options. The existing isolated temp folders for parallel jobs cover collisions.
- Optional skip of already-downloaded items with `--download-archive`.
- Ask for confirmation above a large item count.

**Tests:** picker model tests, job expansion tests and a playlist fixture.

**Done when:** a playlist link can be picked from, queued as many jobs and finished, with History entries for each.

## Phase 7: Browse (Release 3)

**Goal:** turn Search into Browse with a provider selector, without hurting the Twitch flow.

**Work**

- Rename the tab in the rail and `TAB_NAMES`, and the strings in both languages.
- Add a provider selector at the top, shown only when more than one provider has `BROWSE`. With only Twitch it stays as today.
- Twitch Browse stays untouched, including Use this VOD.
- If YouTube browsing is wanted: a YouTube provider with search (`ytsearch`) and channel listing through flat extraction, reusing the VOD list and grid models.

**Tests:** update `test_qt_search_tab.py` and add selector tests.

**Done when:** the Twitch search flow is unchanged and the selector never lists a provider that cannot browse.

## Phase 8: Subscriptions

**Goal:** follow channels from any site and see what is new.

**Work**

- Generalize `core/watchlist.py` from streamers to entries with a provider, a channel URL and the last item seen.
- Check periodically with flat extraction limited to the newest items, and show the notification badge as today.
- Never download automatically. Keep the current rule that the person starts every download.

**Tests:** extend `test_watchlist.py` with non-Twitch entries and old-format files.

**Done when:** existing Twitch watch lists load unchanged, and a pinned YouTube channel shows new items.

## Phase 9: Later (optional)

- Cut editor for non-Twitch sources, using yt-dlp section downloads and the storyboard formats yt-dlp exposes.
- A Home dashboard with a big paste box, recent downloads and new subscription items.
- Rename the internal modules (`luckytwitch_engine`, `luckytwitch_qt`) in one mechanical commit.

## 5. Spikes to do early (during phase 2)

- Run `yt-dlp -J` on real YouTube, TikTok, Instagram and Reddit links and save trimmed outputs as fixtures.
- Confirm whether YouTube needs the external JavaScript runtime with the yt-dlp version the app downloads.
- Find which TikTok and Instagram links need cookies in practice.
- Check how `pick_asset` chooses release files today, before writing the phase 0 change.

## 6. Risks

- **Sites change often.** Keep yt-dlp auto-update, show clear errors and offer a retry after updating.
- **Regressions in Twitch.** Phase 1 changes no behavior, and the existing suite is the guard.
- **Broken updates at rename time.** The phase 0 release exists for this. Never create a new repo with the old name, since it would break the redirect.
- **Link scheme only registered on Windows.** Keep the legacy scheme alias and test it there.
- **Antivirus and SmartScreen warnings** on a renamed installer. Keep the same AppId and publisher name.
- **Legal.** Say in the README that the person is responsible for respecting each site's terms and for having the right to the content.

## 7. Release 1 checklist

- Phases 0 to 5 are done and the suite is green on Windows.
- A Twitch VOD downloads and cuts as before.
- A YouTube and a TikTok link download from a clean install.
- The transitional release updates to LuckyDownloader and keeps settings and history.
- Release notes and both READMEs are updated, with a tagline that says desktop downloader built on yt-dlp, with a Twitch VOD cutter.
