# `.markers.json` format (version 1)

Status: Active (specification v1)

Written by LuckyTwitch Downloader next to each part when **Options → Chapter details → Also export a .markers.json for the LuckyTwitch Premiere plugin** is on. Read by the Premiere Pro panel in [`premiere-plugin-cep/`](../premiere-plugin-cep). This file is the contract between the app and the panel, so a change here means a change on both sides.

The sample `tests/fixtures/markers_sample.json` is checked by the Python tests (it must be exactly what the app writes) and by the panel's tests (it must be readable), so the two cannot drift apart without a test failing. Regenerate it with `python tests/test_premiere_plugin_json.py`.

```json
{
  "format": "luckytwitch-markers",
  "version": 1,
  "name": "Streamer - 2026-01-01 - 1 - part1",
  "duration": 70.0,
  "fps": 29.97,
  "part": { "start": 1200.0, "end": 1270.0 },
  "source": { "url": "...", "vod_id": "1", "title": "...", "streamer": "...", "date": "2026-01-01" },
  "preferences": { "pad_before": 3.0, "pad_after": 3.0 },
  "markers": [
    { "kind": "game", "name": "Just Chatting", "start": 0.0, "end": 50.0, "game": "Just Chatting", "comment": "Game / category" },
    { "kind": "clip", "name": "Funny moment (bob, 120 views)", "start": 7.0, "end": 30.0, "views": 120,
      "comment": "bob · 120 views · https://clips.twitch.tv/c1",
      "clips": [ { "id": "c1", "title": "Funny moment", "creator": "bob", "views": 120, "duration": 20.0, "url": "https://clips.twitch.tv/c1" } ] }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `format` | Always `"luckytwitch-markers"`. The plugin refuses anything else. |
| `version` | Layout version. The plugin refuses a file newer than it understands and says to update. Adding optional fields does not bump it; removing or changing the meaning of a field does. |
| `name` | The part's file name without extension. |
| `duration` | Real length of the part in seconds. |
| `fps` | Frame rate read from the part with ffprobe (30 if it could not be read). |
| `part.start` / `part.end` | Where the part sits in the original VOD, in seconds. Useful to line up the chat file, whose times count from the start of the VOD. |
| `source` | The VOD the part came from (omitted if unknown). |

| `preferences` | Optional object giving starting defaults for the Premiere panel (e.g. `pad_before`, `pad_after`). |
| `markers[].kind` | `"game"` (a game / category stretch), `"clip"` (a Twitch clip) or `"muted"` (a stretch Twitch silenced, see below). A plugin that does not know a kind must skip it, not fail. |
| `markers[].start` / `end` | Seconds **from the start of the part** (not the VOD). `end > start` for a range; a marker can also be a single point. |
| `markers[].name` | Clip: the title built from the chapter title template. Game: the game's name, with no `GAME:` prefix (the plugin adds it if asked). Muted: always `"Muted audio"`. |
| `markers[].comment` | Text for the marker's comment field. Muted: `"Silenced by Twitch (usually copyrighted audio)"`. |
| `markers[].views` | Clips only. Total views of the clip (the largest, if several clips were merged into one chapter). |
| `markers[].game` | Games only. The game's name. |
| `markers[].clips` | Clips only. Every Twitch clip behind the marker (several when overlapping clips were merged). |

Markers are sorted by start time (game markers first when they start together). Colors are **not** in the file on purpose: the plugin chooses them from `kind` and `views`, so you can change the scheme without re-downloading.

## Muted markers (`kind: "muted"`)

Twitch silences copyrighted audio in a VOD, in whole HLS segments (10 s each; in practice usually 3-minute blocks). LuckyTwitch reads which segments are silenced from the VOD's playlist (a silenced segment is named `<n>-muted.<ext>`, e.g. `522-muted.mp4`) when you press **Get info**, merges touching segments into one stretch, and writes each stretch that overlaps a part as one marker. They are written only when **Options → Premiere Pro → Muted audio** is on (it needs the plugin file option on too).

```json
{ "kind": "muted", "name": "Muted audio", "start": 12.0, "end": 30.0, "comment": "Silenced by Twitch (usually copyrighted audio)" }
```

- `start` / `end` are seconds from the start of the part, like every other marker, and are cut at the part's edges (a stretch that begins before the part starts at `0`).
- A muted marker has no `views`, `game` or `clips`.
- **`version` stays `1`.** The plugin refuses any file with a higher version, so bumping it would stop the current plugin from opening these files at all. Muted markers are supported by the plugin (`KNOWN_KINDS` includes `muted`, with `importMuted: true` and red marker color by default).
- The sample is `tests/fixtures/markers_sample_muted.json` (checked by the Python tests: it must be exactly what the app writes). `markers_sample.json`, the one the plugin's own tests read, is deliberately unchanged and has no muted marker.

Muted markers are accepted by the validation in `markers-core.js` and imported as red markers when the plugin panel setting `importMuted` is enabled.
