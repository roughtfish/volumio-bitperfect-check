# Volumio bit-perfect check

Two small tools for [Volumio](https://volumio.com) that show what's playing and confirm that the audio reaching your USB DAC is bit-perfect.

- **[Now-playing TV page](#now-playing-tv-page)**: a full-screen page served by the Volumio device itself, for a TV or any browser. It shows album art, the source and DAC formats, a bit-perfect badge, your Discogs vinyl collection and your Last.fm play history.
- **[Windows terminal check](#windows-terminal-check)**: a double-click script for a Windows PC that shows the same bit-perfect information in a terminal window, with album art.

![Now-playing page showing album art, formats, bit-perfect badge, vinyl and Last.fm details](docs/screenshot.png)

---

## Now-playing TV page

A Python web server that runs on the Volumio device and serves a now-playing page at `http://<volumio-address>:8080`. It's designed for a TV browser, but works in any browser on your network.

### What it shows

- **Album art** with a blurred, slowly moving background, and accent colours picked from the cover
- **Track, artist and album**, with long titles resized to fit
- **A progress bar** with elapsed time and track length
- **Source and DAC formats**: what Volumio is receiving and what is actually sent to the DAC
- **A bit-perfect badge**: green when the two match, red if something is resampling
- **The LED colour an iFi Zen DAC V2 should show** for the current format, with the DAC's firmware version detected automatically (only shown when an iFi DAC is connected)
- **Discogs** (optional):
  - **Owned on vinyl**: when the track or album is in your collection, with the pressing, the date you added it, and its current value (VG+ price suggestion, lowest listing and number for sale)
  - **Not owned on vinyl**: the lowest current price for a vinyl copy, and how many other records you own by the artist
- **Last.fm** (optional): your play counts for the track, album and artist, whether you've loved the track, when you first scrobbled it, and when you last played it
- **Up next**: the next tracks in Volumio's queue (not available with Tidal Connect, where the queue lives in the Tidal app)

It also keeps LG TVs from dropping into their screen-saver (see [LG TV keep-alive](#lg-tv-keep-alive)), drifts the layout slightly to reduce the risk of burn-in, and reloads itself every 6 hours.

### Requirements

- A Volumio device with **Python 3.7 or newer** (included with Volumio 3)
- **SSH enabled on Volumio**: open `http://<your-volumio>.local/dev` and click **Enable** next to SSH
- **Optional:** a [Discogs personal access token](https://www.discogs.com/settings/developers) and a [Last.fm API key](https://www.last.fm/api/account/create)

### Setup

1. Download the files in the `nowplaying` folder.
2. Copy `config.example.json` to `config.json` and fill in your details (see [Configuration](#configuration)). You can leave the Discogs or Last.fm details blank to switch those features off.
3. From the folder with the files, copy them to Volumio. The default password is `volumio`:
   ```
   scp nowplaying.py config.json nowplaying.service volumio@<volumio-address>:~/
   ```
4. Log in to Volumio:
   ```
   ssh volumio@<volumio-address>
   ```
5. Install the page as a service, so it starts automatically:
   ```
   mkdir -p ~/nowplaying
   mv -f ~/nowplaying.py ~/config.json ~/nowplaying/
   sudo mv -f ~/nowplaying.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now nowplaying
   ```
6. Open `http://<volumio-address>:8080` on your TV. Many TV browsers can't resolve `.local` names, so use the device's IP address, which you can find in Volumio under **Settings → Network**.

### Updating

After changing `nowplaying.py` or `config.json`, copy them over again and restart the service:

```
scp nowplaying.py config.json volumio@<volumio-address>:~/nowplaying/
ssh -t volumio@<volumio-address> "sudo systemctl restart nowplaying"
```

On Windows, `deploy.bat` does both in one double-click. Edit the `HOST` line to your Volumio's IP address first. It needs [PuTTY](https://www.putty.org) installed.

Reload the page on the TV afterwards, since it keeps the old version open until you do.

### Configuration

`config.json` sits next to `nowplaying.py` and keeps your keys out of the code:

```json
{
  "discogs_user": "your-discogs-username",
  "discogs_token": "your-discogs-token",
  "lastfm_user": "your-lastfm-username",
  "lastfm_api_key": "your-lastfm-api-key",
  "currency": "GBP",
  "tv_keepalive": true,
  "tv_keepalive_only_when_playing": true,
  "tv_keepalive_input": "move"
}
```

| Setting          | What it does                                                           |
|------------------|------------------------------------------------------------------------|
| `discogs_user`   | Your Discogs username, for the vinyl badges                            |
| `discogs_token`  | Discogs personal access token (needed for private collections and prices) |
| `lastfm_user`    | Your Last.fm username, for play counts and history                     |
| `lastfm_api_key` | Last.fm API key (the key, not the shared secret)                       |
| `currency`       | Currency for Discogs prices, such as `GBP`, `USD` or `EUR`             |
| `tv_keepalive`   | Stop an LG TV's screen-saver while the page is open (`true` or `false`) |
| `tv_keepalive_only_when_playing` | Only keep the TV awake while music is playing, so the screen-saver still runs when paused |
| `tv_keepalive_input` | What to send the TV: `move` (a one-pixel pointer nudge) or a remote button name such as `BLUE` |

A few other options are near the top of `nowplaying.py`, including the port (`PORT = 8080`) and how often the page updates (`REFRESH_SECONDS = 5`).

**Never commit `config.json` or `lgtv_key.json`.** They contain your tokens and your TV's pairing key. The included `.gitignore` keeps them, and the Discogs cache files, out of the repository.

### LG TV keep-alive

LG webOS TVs start a screen-saver after a couple of minutes in the built-in web browser, and it can't be turned off in the TV's settings. To stop it, the page can send the TV a tiny pointer nudge over your network every minute, the same way phone remote apps do.

- **The TV is found automatically.** When the LG browser opens the page, the server notes its address. Other browsers, such as your laptop's, are ignored. To set it yourself, add `"tv_ip": "192.168.1.x"` to `config.json`.
- **It only runs while the page is open on the TV,** and by default only while music is playing, so the screen-saver still protects the screen when you pause.

To set it up:

1. On the TV, allow control over the network. On recent LG models this is under **Settings → General → Devices → External Devices**, called **LG Connect Apps** or similar.
2. Open the page on the TV and play something. Within about a minute, the TV asks whether to allow **Volumio now playing**. Accept it with the remote. The pairing is saved in `lgtv_key.json`, so you only do this once.
3. Check `http://<volumio-address>:8080/api/tv`. It should show `"paired": true` and the status **Keeping the TV awake**.

If the pointer flickers on screen, set `tv_keepalive_input` to a button the page ignores, such as `"BLUE"`. On an OLED, keeping the same layout on screen for hours still carries some risk of burn-in, even with the drift, so keep the brightness moderate and turn the TV off when you're not listening.

### Troubleshooting

- **Page won't load:** check the service is running with `systemctl status nowplaying`, and view its log with `journalctl -u nowplaying -n 30 --no-pager`.
- **No vinyl badges:** open `http://<volumio-address>:8080/api/discogs`. It shows how many releases loaded and any error. Give it a minute after starting, because it downloads your collection first.
- **No Last.fm badge:** check the log with `journalctl -u nowplaying -n 30 --no-pager` for Last.fm errors, and make sure you used the API key rather than the shared secret.
- **LG screen-saver still appears:** check `http://<volumio-address>:8080/api/tv`. The `status` and `error` lines show whether the TV was found, paired and nudged. If the TV never asked for permission, check network control is enabled on the TV (step 1 of [LG TV keep-alive](#lg-tv-keep-alive)). For other TVs, running the page on a streaming stick with a kiosk browser (for example Fully Kiosk Browser with "Keep screen on") is more reliable.
- **Stopped working after a Volumio update:** major updates can remove the service file. Repeat step 5 of Setup.

---

## Windows terminal check

A double-click Windows script, `check-volumio.bat`, that shows the same bit-perfect information in a terminal window and refreshes automatically.

### What it shows

- **Track, artist and album**, from Volumio's API
- **What Volumio is receiving**: the sample rate and bit depth of the source
- **What is sent to the DAC**: the actual sample rate and bit depth, read from ALSA on the Volumio device
- **Album art**: a real image in Windows Terminal (using Sixel), or coloured block art anywhere else
- **The LED colour an iFi Zen DAC V2 should show** for the current format, with the DAC's firmware version detected automatically (only shown when an iFi DAC is connected)

If the "receiving" and "sent to the DAC" values match, nothing is resampling the audio along the way.

### Requirements

- **Windows 10 or 11**
- **PuTTY**, for the `plink` command: [putty.org](https://www.putty.org)
- **SSH enabled on Volumio** (see above)
- **Windows Terminal 1.22 or newer** for the real album art image. Older terminals fall back to block art automatically.

### Setup

1. Download `check-volumio.bat`.
2. Open it in a text editor and change the settings at the top to match your system.
3. **First run only:** open Command Prompt, run `plink volumio@<volumio-address>`, press **y** to accept the host key, then close the window.
4. Start playing something on Volumio, then double-click `check-volumio.bat`.

### Settings

| Setting      | Default           | What it does                                                             |
|--------------|-------------------|--------------------------------------------------------------------------|
| `$vol`       | `volumiopc.local` | Your Volumio device's hostname or IP address                             |
| `$user`      | `volumio`         | SSH username                                                             |
| `$pass`      | `volumio`         | SSH password (Volumio's default)                                         |
| `$artMode`   | `auto`            | `sixel` for a real image, `blocks` for coloured blocks, `auto` to choose |
| `$artPx`     | `288`             | Sixel image size in pixels (keep it a multiple of 6)                     |
| `$artWidth`  | `48`              | Block art width in characters                                            |
| `$infoWidth` | `58`              | Maximum width of the text column                                         |
| `$refresh`   | `20`              | Seconds between refreshes                                                |

Press any key to refresh straight away, or **Ctrl+C** to quit.

The password is stored in plain text in the file. That's fine for Volumio's default password on a home network, but don't use a password here that you use anywhere else.

### Troubleshooting

- **"Could not connect":** check the Volumio device is on, SSH is enabled, and you've accepted the host key once (step 3 of Setup).
- **Gibberish instead of album art:** your terminal doesn't support Sixel. Update Windows Terminal, or set `$artMode = 'blocks'`.
- **Image overlapping text or cut off:** make the window wider, or reduce `$artPx`.

---

## iFi Zen DAC V2 LED colours

When an iFi DAC is connected, both tools show the LED colour it should display, using the scheme from the Zen DAC V2 manual (v1.4):

| LED    | Format               |
|--------|----------------------|
| Green  | PCM 44.1 to 96 kHz   |
| Yellow | PCM 176.4 to 384 kHz |
| Cyan   | DSD64 / DSD128       |
| Blue   | DSD256               |

### Firmware detection

Both tools read the DAC's firmware version from its USB connection (the `bcdDevice` value, for example `7.6c`) and adjust the note under the LED colour:

| Firmware          | Example | Note shown                                                         |
|-------------------|---------|--------------------------------------------------------------------|
| **'c'** (GTO filter) | `7.6c`  | The GTO filter upsamples inside the DAC, so the real LED shows white whatever the source |
| **'b'** (no MQA)  | `7.6b`  | The LED should match the colour shown                              |
| Standard          | `7.60`  | The LED should match the colour shown                              |

The variant is taken from the last character of the version number, which is how iFi names its firmware. If you switch firmware, the note updates within a minute. The 'c' firmware's upsampling happens inside the DAC, after the data arrives, so it doesn't affect whether playback to the DAC is bit-perfect.

Older manuals use a different colour scheme, so your DAC may not match this table exactly.

## How it works

- Track details and the source format come from Volumio's REST API (`/api/v1/getState` and `/api/v1/getQueue`).
- The format sent to the DAC comes from `/proc/asound/card*/pcm*p/sub0/hw_params` on the Volumio device. The TV page reads it directly, and the Windows script reads it over SSH.
- The iFi firmware version comes from the DAC's USB details in `/sys/bus/usb/devices` (vendor ID `20b1`, the XMOS USB chip iFi uses).
- Vinyl information comes from the Discogs API, and play history from the Last.fm API. Both are cached so the page makes as few requests as possible.
- The LG keep-alive uses the TV's local network control interface (the same one phone remote apps use) to send pointer input.

## Licence

MIT. See [LICENSE](LICENSE).
