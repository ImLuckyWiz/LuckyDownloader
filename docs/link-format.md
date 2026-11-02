# `luckydownloader://` links (version 1)

Status: Active (specification v1)

Any web page, document, chat message or program can offer a link that opens LuckyDownloader with a VOD and its cut points already filled in on the **Plan** tab. This file is the contract between those links and the app. It is meant for people who want to add such a link to their own page or tool.

```
luckydownloader://open?v=1&url=<VOD link>&cuts=<cut points>&label=<name>
```

> **Backward Compatibility:** Legacy `luckytwitch://` links are also accepted as an alias and handled identically.

| Parameter | Required | Meaning |
| --- | --- | --- |
| `url` | yes | The VOD. A Twitch VOD link, or anything else yt-dlp understands. Must start with `http://` or `https://`. |
| `cuts` | no | The cut points, written exactly as in the Plan tab: `0:20:00 to 3:30:00`, `0:00 - 30:00 - 1:30:00 - end`, or several groups separated by `;` or a new line. Empty or missing: the default is the whole VOD. |
| `label` | no | A short name for the job (for example a title). It only appears in the log and the status line. |
| `v` | no | The version of this format. The current one is `1`. A link with a higher number is refused with a message that asks the person to update the app. Parameters the app does not know are ignored, so they can be added later without changing `v`. |

Every value has to be URL-encoded (`encodeURIComponent` in JavaScript). Limits: `url` 2000 characters, `cuts` 2000, `label` 120, the whole link 8000.

## What the app does with a link

1. Brings its window to the front (it starts the app if it is not open; if it is already open, no second window appears).
2. Opens the **Plan** tab, puts the VOD in the VOD box, replaces the cut points with `cuts`, and presses **Get info** for the person.
3. Says so in the status line and the log.

That is all. **A link never adds anything to the queue and never starts a download**: the person checks the cut points and presses the button. A link cannot change any setting, choose a folder or a file name, or run anything else.

If the VOD cannot be read (expired, private, mistyped), the usual error is shown and nothing stays loaded, so the cut points of the link cannot end up applied to a VOD that was open before.

## Links that are refused

The app shows a message and changes nothing when the link:

- is not `luckydownloader:` (or `luckytwitch:`), or asks for an action other than `open`;
- has no `url`, or a `url` that is not `http(s)`, has spaces, or contains a user name or password;
- points to this computer or a private network (`localhost`, `127.x`, `10.x`, `192.168.x`, `*.local`...);
- has a value over the limits above, or a `v` newer than the app understands.

Control characters are removed from every value.

## Examples

HTML:

```html
<a href="luckydownloader://open?v=1&url=https%3A%2F%2Fwww.twitch.tv%2Fvideos%2F123456789&cuts=0%3A20%3A00%20to%203%3A30%3A00&label=Big%20Stream">
  Open in LuckyDownloader
</a>
```

JavaScript:

```js
function luckyDownloaderLink(vodUrl, cuts, label) {
  var q = ["v=1", "url=" + encodeURIComponent(vodUrl)];
  if (cuts) q.push("cuts=" + encodeURIComponent(cuts));
  if (label) q.push("label=" + encodeURIComponent(label));
  return "luckydownloader://open?" + q.join("&");
}
```

Python: `weblink.build_link(url, cuts, label)` in this repository builds the same link, and `weblink.parse_link(text)` is the function the app uses to read one.

A page cannot know whether the app is installed, so it is kind to say, next to the link, that it needs LuckyDownloader and to link to the download page. The browser may ask for permission the first time ("Open LuckyDownloader?"); choosing to always allow it for that site makes later clicks immediate.

## How the system finds the app

- **Windows:** the installer has an option, ticked by default, that registers both `luckydownloader:` and `luckytwitch:` schemes for the current user (no administrator rights). If you run the portable folder or run from source, **Options → Tools → Links from web pages → Set up links** does the same. The same button says when the links currently open another copy of the app, and takes them over.
- **macOS:** the app bundle declares both schemes in `CFBundleURLSchemes`. macOS learns about it when the app is in Applications; if a link does nothing, open LuckyDownloader once from Applications and try again.
- **Linux:** the desktop file handles both schemes via `MimeType=x-scheme-handler/luckydownloader;x-scheme-handler/luckytwitch;`.

Registering is per user and can be undone: on Windows delete the keys `HKEY_CURRENT_USER\Software\Classes\luckydownloader` and `HKEY_CURRENT_USER\Software\Classes\luckytwitch` (uninstalling the app does it too).

## One window only

The browser starts the program again for every click. A second launch does not open a second window: it leaves the link as a small file in the `links` folder of the app's data folder (see the README) and the open window picks it up within half a second. If the open window does not answer within three seconds, the new launch opens its own window and uses the link itself. Nothing listens on the network.
