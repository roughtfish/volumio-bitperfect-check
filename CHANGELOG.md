# Changelog

All notable changes to this project are listed here. The version number is shown at the bottom of the now-playing page's settings page, and the installer reports it when it finishes.

Version numbers follow the pattern **major.minor.fix**:

- **Fix** (1.0.**1**): bug fixes only
- **Minor** (1.**1**.0): new features that work with your existing settings
- **Major** (**2**.0.0): changes that need you to redo part of your setup

To update, run the installer again. Your settings are kept.

## 1.8.0 (27 September 2026)

### Added

- **Update notice:** the settings page shows a banner when a newer version is on GitHub, with the main changes and the command to update. It checks GitHub's changelog a minute after starting and every 6 hours, and there's a **Check now** link. Nothing is downloaded or installed automatically.
- **Check GitHub for new versions** on the settings page turns the check off.

## 1.7.0 (27 September 2026)

### Added

- **Stuck-Volumio warning:** the status dot turns amber if Volumio seems stuck, by comparing what Volumio says with what's actually reaching the DAC:
  - Volumio says it's playing, but nothing has reached the DAC for 30 seconds
  - music is reaching the DAC, but Volumio has said it's stopped or paused for 30 seconds
  - the reported track keeps flipping back and forth (three returns within a minute)
  It uses the DAC's running state rather than just whether it's connected, so pausing doesn't trigger it, and it clears by itself once things match again.
- **Restart Volumio** button on the settings page, which restarts the Volumio PC through Volumio's live connection, the same way its own interface does, so there's no need for SSH.

## 1.6.0 (27 September 2026)

### Added

- **Instant updates:** the page now keeps a live connection to Volumio, the same one Volumio's own web interface uses, and Volumio announces every change as it happens. Track changes, pause and play reach the TV within about half a second, instead of up to about 8 seconds.
- Both the older and newer versions of Volumio's live-update protocol (socket.io 2 and 3+) are supported, so a Volumio update is less likely to stop it working.
- If the live connection isn't available, the page falls back to regular checks automatically and keeps trying to reconnect. The status dot shows "Live updates off: checking every few seconds" if it has been off for more than 2 minutes.
- The settings page's status table shows whether live updates are on, and `/api/live` shows more detail.

### Changed

- With live updates on, Volumio is only checked every 30 seconds as a backstop, and pages only check every 10 seconds, so there are far fewer requests.

## 1.5.1 (27 September 2026)

### Fixed

- **TV screen-off on newer LG TVs** (such as the 2025 C5), which refuse the screen commands when asked directly ("404 no such service or method"). The page now also sends them through a blank on-screen notification that's opened and closed at once, the workaround used by other LG remote tools, and remembers whichever method works. You may see a brief flicker as the screen switches off or on.
- `/api/tv` shows which method switched the screen (`screen_method`).

## 1.5.0 (27 September 2026)

### Added

- **Settings backup and restore**, in a new **Backup** section of the settings page:
  - **Download settings with keys:** everything, including your Discogs token, Last.fm key, secret and connection, and TV pairing, so a restore needs nothing re-entered. Keep this file private.
  - **Download without keys:** your settings only, safe to share.
  - **Restore from a backup file:** choose the file and click **Restore**. Restoring a backup made without keys keeps the keys that are already saved.
- Settings backup files (`nowplaying-settings-*.json`) are kept out of the repository by `.gitignore`, and the automatic check fails if one is uploaded.

## 1.4.0 (27 September 2026)

### Added

- **Turn the TV screen off when idle** (LG webOS TVs): after 15 minutes with nothing playing, the page switches the TV's screen off. The TV itself stays on, and the picture comes back as soon as music plays. It only happens while the TV is showing the page, so it never turns the screen off while you're watching something else. Set the time, or 0 for never, under **Turn the TV screen off after** on the settings page. The keep-alive doesn't nudge the TV while the screen is off.

### Changed

- The page now asks the TV for permission to control its screen, as well as remote input. **The TV will ask for permission again** the first time: accept it with the remote. If it doesn't ask, tick **Pair the TV again** on the settings page.

## 1.3.7 (27 September 2026)

### Removed

- The file format on the Source line, added in 1.3.6. Volumio reports the service ("tidal") rather than the actual file format for Tidal, so it couldn't be shown reliably. The Source line shows the quality only, as before.

## 1.3.6 (27 September 2026)

### Added

- **File format on the Source line**, such as **FLAC · 192 kHz / 24-bit**, when Volumio reports a recognised format (FLAC, ALAC, WAV, AIFF, MP3, AAC, Ogg Vorbis, Opus, WavPack, APE or DSD). When Volumio doesn't know the format, as it may not with Tidal Connect, the line stays as before. The Windows script shows it too.

## 1.3.5 (27 September 2026)

### Changed

- **Far fewer requests to Volumio:** one shared background check now asks Volumio what's playing every 3 seconds, and the pages, the scrobbler, the scrobble watcher and the Windows script all use that. Before, each asked separately, up to about 51 times a minute with the TV and a laptop open; now it's about 20, however many screens are open.
- **Smoother on TV browsers:** the page only recalculates its layout and rebuilds "Up next" when something has actually changed, rather than on every update.
- `/api/scrobble` shows how many requests have been made to Volumio since the page started.
- If the Volumio PC's clock jumps backwards (for example when it syncs the time after starting up), the page asks Volumio again rather than keeping old details.

## 1.3.4 (27 September 2026)

### Added

- **"Source unconfirmed"** (amber) replaces "Being resampled" when Volumio reports a track as CD quality (44.1 kHz / 16-bit) but the DAC is receiving more. Volumio sometimes misreports hi-res tracks this way, and CD quality can't become hi-res without resampling, so the source figure is the one that's wrong. Any other mismatch, such as the DAC receiving less than the source, still shows "Being resampled". The Windows script shows the same.

## 1.3.3 (27 September 2026)

### Changed

- **Much lighter on Volumio with long playlists:** "Up next" now fetches Volumio's queue only when the track changes, and every 2 minutes in case the queue was edited, instead of on every page update (every 5 seconds). Long queues can make Volumio sluggish, which can cause lagging track details and delayed scrobbles.

## 1.3.2 (27 September 2026)

### Removed

- The **Full-screen cover** style. If it was selected, the page uses **Normal** instead.

## 1.3.1 (27 September 2026)

### Fixed

- The full-screen cover showed as a black screen, because the hidden keep-awake video was drawn on top of it.

## 1.3.0 (27 September 2026)

### Added

- **Six more cover styles** under **Cover style**:
  - **Duotone:** the cover in two tones of its own main colour
  - **Black and white,** with a light film grain
  - **Halftone:** the cover made of coloured dots, sized by brightness, like printed artwork
  - **CD:** the cover printed on a silver disc, which spins while music plays
  - **Cassette:** the cover as the tape's label, with reels that turn while music plays
  - **Full-screen cover:** the cover fills the whole screen, slowly panning, with the details on a darkened side
- **Gaps between pixels (mosaic look)** for pixel art.

### Changed

- Pixel art is now drawn block by block at full size, so the edges are sharp on every browser, including TVs that smooth scaled images.
- **Pixel size** is now **Pixel and dot size**, and also sets the number of dots across for halftone.

## 1.2.0 (27 September 2026)

### Added

- **Cover styles**, chosen under **Cover style** on the settings page:
  - **Normal:** the album cover as before
  - **Pixel art:** the cover drawn as large square blocks, with the size set under **Pixel size** (8 to 96 blocks across, default 32)
  - **Spinning vinyl:** the cover becomes the centre label of a record that spins at 33⅓ rpm while music plays, and stops when paused
- **Switch to spinning vinyl when I own it on vinyl** (on by default): uses your Discogs collection to show the record whenever the track or album is one you own, whatever the chosen style. The idle screen's suggested record also shows as vinyl, not spinning.

## 1.1.2 (27 September 2026)

### Changed

- The scrobble message now stays on screen for 8 seconds by default instead of 4, so it's easier to notice on a TV.

### Added

- **Scrobble message settings** on the settings page: how long the message shows, from 1 to 60 seconds (0 turns it off), and an option to keep it up until the next track starts.

## 1.1.1 (27 September 2026)

### Fixed

- The scrobble message now appears in the top-left corner, above the album art, so it can't overlap a long track title. The status dot hides while it's showing.
- The scrobble message fades out by itself, even on TV browsers that don't run its timer.
- The same track is never announced twice within 10 minutes, if Volumio briefly re-sends its details.

## 1.1.0 (27 September 2026)

### Added

- **Scrobble confirmations:** a message in the top-right corner, such as "Scrobbled by Tidal: Farewell Transmission", once Last.fm has recorded a scrobble. It works for Tidal Connect (scrobbled by the Tidal app) and Volumio's own playback (scrobbled by this page), by checking your Last.fm recent tracks every 30 seconds while music plays.
- **Missed-scrobble warning:** the status dot turns amber if three tracks in a row, each played past halfway, never reach Last.fm, for example if Tidal's Last.fm connection has dropped. Skipped tracks don't count.
- `/api/scrobble` now also shows the confirmation details.

## 1.0.0 (27 September 2026)

The first versioned release.

### Now-playing TV page

- Full-screen now-playing page served by the Volumio device, for a TV or any browser
- Album art with a blurred, slowly moving background, and accent colours taken from the cover
- Progress bar with elapsed time and track length, matching the Tidal app
- Source and DAC formats, with a bit-perfect badge and an 8-second "Checking..." grace period at the start of each track
- Expected iFi Zen DAC V2 LED colour, with the firmware version and variant detected automatically from USB
- Discogs: "Owned on vinyl" with pressing, date added and current value, or "Not owned on vinyl" with the lowest price to buy
- Last.fm: play counts, loved tracks, and when you first scrobbled and last played each track
- Last.fm scrobbling for everything Volumio plays, skipping Tidal Connect and other "Connect" services
- Up next from Volumio's queue, with the details column resized so it never overlaps
- Idle screen suggesting a random record from your vinyl collection when nothing has played for 2 minutes
- Status dot that turns amber when Discogs, Last.fm, scrobbling or the TV keep-alive needs attention
- LG TV keep-alive that stops the webOS screen-saver, using a pointer nudge or a remote colour button
- Tab icon and title showing the current album cover, track and artist
- Settings page at `/settings`, with a status summary
- One-line installer, `install.sh`, that also handles updates
- Last.fm connection stored separately in `lastfm_session.json`, so replacing `config.json` can't disconnect scrobbling

### Windows terminal check

- `check-volumio.bat` reads everything from the TV page, so it needs no SSH, PuTTY or password
- Real album art in Windows Terminal using Sixel, or coloured block art elsewhere
- Shows the source and DAC formats, bit-perfect status, Zen LED colour, and Discogs and Last.fm details
