# Changelog

All notable changes to this project are listed here. The version number is shown at the bottom of the now-playing page's settings page, and the installer reports it when it finishes.

Version numbers follow the pattern **major.minor.fix**:

- **Fix** (1.0.**1**): bug fixes only
- **Minor** (1.**1**.0): new features that work with your existing settings
- **Major** (**2**.0.0): changes that need you to redo part of your setup

To update, run the installer again. Your settings are kept.

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
