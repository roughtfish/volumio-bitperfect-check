Volumio bit-perfect check

A small Windows script that shows what your Volumio player is playing, and what is actually being sent to your USB DAC, so you can confirm playback is bit-perfect at a glance.

It refreshes automatically and shows the album art right in the terminal.

<!-- Add a screenshot here: drag an image into this file while editing on GitHub -->
What it shows
Track, artist and album, from Volumio's API
What Volumio is receiving: the sample rate and bit depth of the source (for example Tidal via Tidal Connect)
What is sent to the DAC: the actual sample rate and bit depth reaching your DAC, read from ALSA on the Volumio device
Album art: a real image in Windows Terminal (using Sixel), or coloured block art anywhere else
The LED colour an iFi Zen DAC V2 should show for the current format (standard firmware colour scheme)

If the "receiving" and "sent to the DAC" values match, nothing is resampling the audio along the way.

Requirements
Windows 10 or 11
PuTTY, for the plink command: putty.org. The standard installer adds it to your PATH.
SSH enabled on Volumio: open http://<your-volumio>.local/dev in a browser and click Enable next to SSH.
Windows Terminal 1.22 or newer for the real album art image. It is the default terminal in Windows 11 and is available from the Microsoft Store. Older terminals fall back to block art automatically.
Setup
Download check-volumio.bat.
Open it in a text editor and change the settings at the top to match your system (see below).
First run only: open Command Prompt and run the command below, replacing the hostname with yours. Press y to accept Volumio's host key, then close the window.
   plink volumio@volumio.local

The script runs without prompts, so it cannot accept the host key by itself. 4. Start playing something on Volumio, then double-click check-volumio.bat.

Settings

All settings are at the top of the file.

Setting	Default	What it does
$vol	volumiopc.local	Your Volumio device's hostname or IP address
$user	volumio	SSH username
$pass	volumio	SSH password (Volumio's default)
$artMode	auto	sixel for a real image, blocks for coloured blocks, auto to choose
$artPx	288	Sixel image size in pixels (keep it a multiple of 6)
$artWidth	48	Block art width in characters
$infoWidth	58	Maximum width of the text column
$refresh	20	Seconds between refreshes

The password is stored in plain text in the file. That is fine for Volumio's default password on a home network, but don't use a password here that you use anywhere else.

Controls
Any key: refresh now
Ctrl+C: quit
How it works
Track details and the source format come from Volumio's REST API (/api/v1/getState).
The format sent to the DAC comes from /proc/asound/card*/pcm0p/sub0/hw_params on the Volumio device, read over SSH with plink.
Album art is downloaded only when the track changes, resized, and drawn either as a Sixel image or as coloured half-block characters.
The file is a batch/PowerShell hybrid: the first few lines launch the rest as a PowerShell script, so it can be run with a double-click.
iFi Zen DAC V2 LED colours

The expected LED colour uses the scheme from the Zen DAC V2 manual (v1.4):

LED	Format
Green	PCM 44.1 to 96 kHz
Yellow	PCM 176.4 to 384 kHz
Cyan	DSD64 / DSD128
Blue	DSD256

iFi's 'c' firmware variants include the GTO filter, which upsamples inside the DAC, so the real LED shows white regardless of the source. Older manuals also use a different colour scheme, so your DAC may not match this table.

Troubleshooting
"Could not connect": check the Volumio device is on, SSH is enabled at /dev, and you have accepted the host key once (see Setup, step 3).
Gibberish instead of album art: your terminal does not support Sixel. Update Windows Terminal, or set $artMode = 'blocks'.
Image overlapping text or cut off: make the window wider, or reduce $artPx.
SSH stopped working after a Volumio update: updates can switch SSH off again. Re-enable it at /dev.
Licence

MIT. See LICENSE.
