# Changelog

All notable changes to this project are listed here. The version number is shown at the bottom of the now-playing page's settings page, and the installer reports it when it finishes.

Version numbers follow the pattern **major.minor.fix**:

- **Fix** (1.0.**1**): bug fixes only
- **Minor** (1.**1**.0): new features that work with your existing settings
- **Major** (**2**.0.0): changes that need you to redo part of your setup

To update, run the installer again. Your settings are kept.

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
