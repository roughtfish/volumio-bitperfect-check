<# :
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -Command "iex ((Get-Content '%~f0') -join [char]10)"
exit /b
#>

# Volumio bit-perfect check
# The lines above launch this file as a PowerShell script.
#
# Reads everything from the now-playing page running on Volumio
# (see the nowplaying folder), so no SSH, PuTTY or password is needed.

$vol       = 'volumiopc.local'   # your Volumio's hostname or IP address
$port      = 8080                # port of the now-playing page
$artMode   = 'auto'  # 'sixel' = real image, 'blocks' = coloured blocks, 'auto' = sixel in Windows Terminal
$artPx     = 288     # sixel image size in pixels (keep it a multiple of 6)
$artWidth  = 48      # block art width in characters
$infoWidth = 58      # max width of the text column
$refresh   = 20      # seconds between refreshes

$host.UI.RawUI.WindowTitle = 'Volumio bit-perfect check'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Drawing

$base  = "http://${vol}:$port"
$e     = [char]27
$reset = "$e[0m"
$grey  = "$e[38;2;128;128;128m"
function Rgb($r, $g, $b) { return "$e[38;2;$r;$g;${b}m" }
function HexRgb($hex) {
    $h = $hex.TrimStart('#')
    return Rgb ([Convert]::ToInt32($h.Substring(0, 2), 16)) ([Convert]::ToInt32($h.Substring(2, 2), 16)) ([Convert]::ToInt32($h.Substring(4, 2), 16))
}
function Fit($s) { if ($s.Length -gt $infoWidth) { return $s.Substring(0, $infoWidth - 3) + '...' } return $s }

# Add a labelled line, wrapping long text under the label
function Add-Line([ref]$list, $label, $text, $colour = '') {
    $indent = 13
    $width = $infoWidth - $indent
    $words = ("$text" -split ' ') | Where-Object { $_ -ne '' }
    $rows = @()
    $cur = ''
    foreach ($w in $words) {
        if ($cur.Length -eq 0) { $cur = $w }
        elseif (($cur.Length + 1 + $w.Length) -le $width) { $cur += ' ' + $w }
        else { $rows += $cur; $cur = $w }
    }
    if ($cur.Length -gt 0 -or $rows.Count -eq 0) { $rows += $cur }
    $first = $true
    foreach ($r in $rows) {
        if ($first) { $list.Value += $colour + $label.PadRight($indent) + $r + $reset; $first = $false }
        else { $list.Value += $colour + (' ' * $indent) + $r + $reset }
    }
}

# ---------- Sixel encoder (compiled C# for speed) ----------
$sixelCode = @'
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Text;

public static class SixelEncoder {
    static readonly int[,] Bayer = { {0,8,2,10}, {12,4,14,6}, {3,11,1,9}, {15,7,13,5} };

    static int Quant(int v, int levels, double d) {
        int q = (int)Math.Round(v / 255.0 * levels + d);
        if (q < 0) q = 0;
        if (q > levels) q = levels;
        return q;
    }

    public static string Encode(Bitmap src) {
        int w = src.Width, h = src.Height;
        BitmapData data = src.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb);
        int stride = data.Stride;
        byte[] px = new byte[stride * h];
        Marshal.Copy(data.Scan0, px, 0, px.Length);
        src.UnlockBits(data);

        // Quantise to a 6x7x6 colour cube with ordered dithering
        int[] idx = new int[w * h];
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                int o = y * stride + x * 3;
                double d = (Bayer[y & 3, x & 3] + 0.5) / 16.0 - 0.5;
                int r = Quant(px[o + 2], 5, d);
                int g = Quant(px[o + 1], 6, d);
                int b = Quant(px[o], 5, d);
                idx[y * w + x] = r * 42 + g * 6 + b;
            }
        }

        StringBuilder sb = new StringBuilder();
        sb.Append("\u001bP0;1;0q");
        sb.Append("\"1;1;").Append(w).Append(';').Append(h);
        for (int r = 0; r <= 5; r++)
            for (int g = 0; g <= 6; g++)
                for (int b = 0; b <= 5; b++)
                    sb.Append('#').Append(r * 42 + g * 6 + b).Append(";2;")
                      .Append(r * 100 / 5).Append(';').Append(g * 100 / 6).Append(';').Append(b * 100 / 5);

        int[] bits = new int[252 * w];
        bool[] used = new bool[252];
        List<int> list = new List<int>();

        for (int band = 0; band < h; band += 6) {
            for (int k = 0; k < 6 && band + k < h; k++) {
                int y = band + k;
                for (int x = 0; x < w; x++) {
                    int c = idx[y * w + x];
                    if (!used[c]) { used[c] = true; list.Add(c); }
                    bits[c * w + x] |= 1 << k;
                }
            }
            bool first = true;
            foreach (int c in list) {
                if (!first) sb.Append('$');
                first = false;
                sb.Append('#').Append(c);
                int x = 0;
                while (x < w) {
                    int v = bits[c * w + x];
                    int run = 1;
                    while (x + run < w && bits[c * w + x + run] == v) run++;
                    char ch = (char)(63 + v);
                    if (run > 3) sb.Append('!').Append(run).Append(ch);
                    else sb.Append(ch, run);
                    x += run;
                }
                Array.Clear(bits, c * w, w);
                used[c] = false;
            }
            list.Clear();
            sb.Append('-');
        }
        sb.Append("\u001b\\");
        return sb.ToString();
    }
}
'@

if ($artMode -eq 'auto') { if ($env:WT_SESSION) { $artMode = 'sixel' } else { $artMode = 'blocks' } }
if ($artMode -eq 'sixel') {
    try { Add-Type -TypeDefinition $sixelCode -ReferencedAssemblies System.Drawing -ErrorAction Stop }
    catch { $artMode = 'blocks' }
}

# ---------- Album art ----------
$script:artUrl = ''
$script:artCache = $null

function Get-ResizedImage($url, $size) {
    $bytes = (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5).Content
    $ms  = New-Object IO.MemoryStream(,$bytes)
    $src = [Drawing.Image]::FromStream($ms)
    $bmp = New-Object Drawing.Bitmap($size, $size, [Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $g = [Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.PixelOffsetMode   = [Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.SmoothingMode     = [Drawing.Drawing2D.SmoothingMode]::HighQuality
    $g.DrawImage($src, 0, 0, $size, $size)
    $g.Dispose(); $src.Dispose(); $ms.Dispose()
    return $bmp
}

function Get-AlbumArt($url) {
    if (-not $url) { return $null }
    if ($url.StartsWith('/')) { $url = "$base$url" }
    if ($url -eq $script:artUrl) { return $script:artCache }

    $result = $null
    try {
        if ($artMode -eq 'sixel') {
            $bmp = Get-ResizedImage $url $artPx
            $result = [SixelEncoder]::Encode($bmp)
            $bmp.Dispose()
        } else {
            $w = $artWidth
            $bmp = Get-ResizedImage $url $w
            $block = [char]0x2580
            $lines = @()
            for ($y = 0; $y -lt $w; $y += 2) {
                $sb = New-Object Text.StringBuilder
                for ($x = 0; $x -lt $w; $x++) {
                    $t = $bmp.GetPixel($x, $y)
                    $b = $bmp.GetPixel($x, $y + 1)
                    [void]$sb.Append("$e[38;2;$($t.R);$($t.G);$($t.B)m$e[48;2;$($b.R);$($b.G);$($b.B)m$block")
                }
                [void]$sb.Append($reset)
                $lines += $sb.ToString()
            }
            $bmp.Dispose()
            $result = $lines
        }
    } catch {
        $result = $null
    }
    $script:artUrl = $url
    $script:artCache = $result
    return $result
}


function Format-Time($sec) {
    $sec = [math]::Max(0, [math]::Floor($sec))
    return '{0}:{1:00}' -f [math]::Floor($sec / 60), ($sec % 60)
}

# ---------- Main loop ----------
[Console]::Write("$e[?25l")   # hide the cursor
try {
while ($true) {
    $info = @()
    $info += 'Volumio bit-perfect check - ' + (Get-Date -Format 'dd/MM/yyyy HH:mm')
    $info += ''
    $art = $null

    try {
        $s = Invoke-RestMethod -Uri "$base/api/status" -TimeoutSec 5
    } catch {
        $s = $null
        $info += 'Could not reach the now-playing page at ' + $base
        $info += 'Check Volumio is on and the page is installed'
        $info += '(see the nowplaying folder in the README).'
    }

    if ($s -and -not $s.ok) {
        $info += 'The page is running, but it could not reach Volumio.'
    } elseif ($s) {
        $art = Get-AlbumArt $s.albumart
        if ($s.status -ne 'play') { $info += 'Volumio is not playing right now.'; $info += '' }
        $info += Fit ('Track:       ' + $s.title)
        $info += Fit ('Artist:      ' + $s.artist)
        $info += Fit ('Album:       ' + $s.album)
        if ($s.duration) {
            $el = [math]::Min($s.seek / 1000, $s.duration)
            $info += 'Position:    ' + (Format-Time $el) + ' / ' + (Format-Time $s.duration)
        }
        $info += ''

        $src = '-'
        if ($s.source -and $s.source.label) { $src = $s.source.label }
        Add-Line ([ref]$info) 'Source:' $src
        if ($s.dac) {
            Add-Line ([ref]$info) 'To DAC:' $s.dac.label
        } else {
            Add-Line ([ref]$info) 'To DAC:' 'Idle'
        }

        if ($s.bitperfect -eq $true) {
            $info += (Rgb 92 240 154) + 'Bit-perfect' + $reset
        } elseif ($s.bitperfect -eq $false) {
            $info += (Rgb 255 138 112) + 'Being resampled' + $reset
        } elseif ($s.dac) {
            $info += $grey + 'Checking...' + $reset
        }

        # Zen LED, only when an iFi DAC is connected
        if ($s.firmware -and $s.dac) {
            $info += ''
            $led = $s.dac.led
            $info += 'Zen LED:     ' + (HexRgb $led.hex) + $led.name + $reset + " ($($led.desc))"
            if ($s.firmware.upsamples) {
                $note = "Firmware $($s.firmware.version) ('c', GTO filter) upsamples, so the real LED shows white."
            } else {
                $note = "Firmware $($s.firmware.version) - the LED should match."
            }
            Add-Line ([ref]$info) '' $note $grey
        }

        # Discogs
        if ($s.vinyl -and $s.vinyl.level -and $s.vinyl.level -ne 'none') {
            $info += ''
            $vc = Rgb 205 178 255
            if ($s.vinyl.level -eq 'notowned') { $vc = Rgb 255 194 122 }
            if ($s.vinyl.level -eq 'artist')   { $vc = Rgb 200 200 200 }
            $info += $vc + $s.vinyl.label + $reset
            Add-Line ([ref]$info) '' $s.vinyl.text
            if ($s.vinyl.price) { Add-Line ([ref]$info) '' $s.vinyl.price $grey }
        }

        # Last.fm
        if ($s.lastfm -and $s.lastfm.text) {
            $info += ''
            $lab = 'Last.fm'
            if ($s.lastfm.loved) { $lab += ' ' + [char]0x2665 }
            $info += (Rgb 255 138 128) + $lab + $reset
            Add-Line ([ref]$info) '' $s.lastfm.text
            if ($s.lastfm.history) { Add-Line ([ref]$info) '' $s.lastfm.history $grey }
        }
    }

    $info += ''
    $info += "Refreshes every $refresh seconds."
    $info += 'Any key = refresh now, Ctrl+C = quit.'

    # ---------- Draw ----------
    Clear-Host
    if ($artMode -eq 'sixel') {
        # Text on the left, real image on the right
        [Console]::Write(($info -join "`n"))
        if ($art) {
            $col = $infoWidth + 4
            [Console]::Write("$e[1;${col}H" + $art)
        }
    } else {
        # Block art on the left, text on the right
        $lines = @()
        if ($art) { $lines = $art }
        $rows = [math]::Max($lines.Count, $info.Count)
        $pad  = ' ' * $artWidth
        $sb = New-Object Text.StringBuilder
        for ($i = 0; $i -lt $rows; $i++) {
            if ($lines.Count -gt 0) {
                if ($i -lt $lines.Count) { [void]$sb.Append($lines[$i]) } else { [void]$sb.Append($pad) }
                [void]$sb.Append('   ')
            }
            if ($i -lt $info.Count) { [void]$sb.Append($info[$i]) }
            [void]$sb.Append("`n")
        }
        [Console]::Write($sb.ToString())
    }

    # Wait for the refresh interval, or until a key is pressed
    for ($i = 0; $i -lt ($refresh * 10); $i++) {
        if ([Console]::KeyAvailable) { [void][Console]::ReadKey($true); break }
        Start-Sleep -Milliseconds 100
    }
}
} finally {
    [Console]::Write("$e[?25h")   # show the cursor again
}
