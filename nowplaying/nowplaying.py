#!/usr/bin/env python3
"""
Volumio now-playing page with bit-perfect check.

Runs on the Volumio device and serves a full-screen page for a TV browser:
  http://<volumio-host>:8080

Uses only the Python standard library.
"""

import base64
import glob
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8080
VOLUMIO_API = "http://localhost:3000/api/v1/getState"
VOLUMIO_QUEUE = "http://localhost:3000/api/v1/getQueue"
REFRESH_SECONDS = 5  # how often the page polls for updates

# Discogs settings live in config.json next to this script, so they stay
# out of the code (and out of GitHub). Example config.json:
#   {"discogs_user": "your-username", "discogs_token": "your-token"}
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = {}
try:
    with open(os.path.join(HERE, "config.json")) as f:
        CONFIG = json.load(f)
except (OSError, ValueError):
    pass
DISCOGS_USER = CONFIG.get("discogs_user", "")
DISCOGS_TOKEN = CONFIG.get("discogs_token", "")
CURRENCY = CONFIG.get("currency", "GBP")
LASTFM_USER = CONFIG.get("lastfm_user", "")
LASTFM_KEY = CONFIG.get("lastfm_api_key", "")
if LASTFM_KEY.startswith("PASTE"):
    LASTFM_KEY = ""                  # placeholder not filled in yet
if DISCOGS_TOKEN.startswith("PASTE"):
    DISCOGS_TOKEN = ""
if DISCOGS_USER.startswith("your-"):
    DISCOGS_USER = ""
if LASTFM_USER.startswith("your-"):
    LASTFM_USER = ""
LASTFM_REFRESH_MINUTES = 5   # re-check play counts this often for the current track
PRICE_REFRESH_HOURS = 24
COLLECTION_REFRESH_HOURS = 6


def read_dac():
    """Return the format currently being sent to the DAC, or None if idle."""
    for path in sorted(glob.glob("/proc/asound/card*/pcm*p/sub0/hw_params")):
        try:
            with open(path) as f:
                text = f.read()
        except OSError:
            continue
        if text.strip() == "closed":
            continue
        fmt = re.search(r"^format:\s*(\S+)", text, re.M)
        rate = re.search(r"^rate:\s*(\d+)", text, re.M)
        if not rate:
            continue
        fmt = fmt.group(1) if fmt else ""
        rate = int(rate.group(1))

        if fmt.startswith("DSD"):
            bits_per_frame = 32
            if fmt.startswith("DSD_U8"):
                bits_per_frame = 8
            elif fmt.startswith("DSD_U16"):
                bits_per_frame = 16
            multiple = round(rate * bits_per_frame / 44100)
            return {
                "rate_khz": None,
                "depth": 1,
                "label": "DSD%d" % multiple,
                "dsd": multiple,
                "led": led_colour(True, rate, multiple),
            }

        depth = None
        m = re.match(r"S(\d+)", fmt)
        if m:
            depth = int(m.group(1))
        khz = rate / 1000.0
        return {
            "rate_khz": khz,
            "depth": depth,
            "label": "%s kHz / %s-bit" % (fmt_khz(khz), depth if depth else "?"),
            "dsd": None,
            "led": led_colour(False, rate, None),
        }
    return None


def led_colour(is_dsd, rate, multiple):
    """Expected LED colour on an iFi Zen DAC V2 (standard firmware, manual v1.4)."""
    if is_dsd:
        if multiple and multiple >= 256:
            return {"name": "Blue", "hex": "#4682ff", "desc": "DSD256"}
        return {"name": "Cyan", "hex": "#00d2e6", "desc": "DSD64/128"}
    if rate <= 96000:
        return {"name": "Green", "hex": "#00d200", "desc": "PCM 44.1-96 kHz"}
    return {"name": "Yellow", "hex": "#ebd700", "desc": "PCM 176.4-384 kHz"}


def fmt_khz(khz):
    if khz is None:
        return "?"
    return ("%.1f" % khz).rstrip("0").rstrip(".")


def parse_number(text):
    m = re.search(r"[\d.]+", text or "")
    return float(m.group(0)) if m else None


# ---------------- Discogs collection ----------------

REMASTER_WORDS = r"(remaster|version|mix|edit|mono|stereo|deluxe|edition|live|bonus|anniversary|expanded)"


def norm(text):
    """Normalise a title or name for matching."""
    s = (text or "").lower()
    s = re.sub(r"\s*[\(\[][^\)\]]*" + REMASTER_WORDS + r"[^\)\]]*[\)\]]", "", s)
    s = re.sub(r"\s+-\s+[^-]*" + REMASTER_WORDS + r".*$", "", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"^the ", "", s)
    return s


def clean_artist(name):
    """Discogs adds '*' and ' (2)' style suffixes to some artist names."""
    return re.sub(r"\s*\(\d+\)$", "", (name or "").replace("*", "")).strip()


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def format_added(stamp):
    """Turn Discogs' '2019-05-12T08:41:22-07:00' into '12 May 2019'."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", stamp or "")
    if not m:
        return ""
    return "%d %s %s" % (int(m.group(3)), MONTHS[int(m.group(2)) - 1], m.group(1))


SYMBOLS = {"GBP": "\u00a3", "USD": "$", "EUR": "\u20ac", "JPY": "\u00a5", "AUD": "A$", "CAD": "C$"}


def money(obj):
    """Format {'value': 12.5, 'currency': 'GBP'} as '\u00a312.50'."""
    if not obj or obj.get("value") is None:
        return ""
    cur = obj.get("currency") or CURRENCY
    return "%s%.2f" % (SYMBOLS.get(cur, cur + " "), float(obj["value"]))


def contains_words(haystack, needle):
    return bool(needle) and (" %s " % needle) in (" %s " % haystack)


class Discogs:
    def __init__(self, user, token):
        self.user = user
        self.token = token
        self.lock = threading.Lock()
        self.releases = []                  # collection, basic info
        self.tracklists = {}                # release id -> [normalised titles]
        self.queue = []                     # release ids waiting for a tracklist
        self.prices = {}                    # release id -> marketplace info
        self.price_queue = []               # release ids waiting for prices
        self.price_file = os.path.join(HERE, "discogs_prices.json")
        self.buy = {}                       # "artist|album" -> cost-to-buy info
        self.buy_queue = []
        self.error = ""                     # last error, shown at /api/discogs
        self.last_sync = ""
        self.coll_file = os.path.join(HERE, "discogs_collection.json")
        self.tl_file = os.path.join(HERE, "discogs_tracklists.json")
        self._load_cache()
        if user:
            threading.Thread(target=self._collection_loop, daemon=True).start()
            threading.Thread(target=self._tracklist_loop, daemon=True).start()

    # --- HTTP ---
    def _get(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "VolumioNowPlaying/1.0"})
        if self.token:
            req.add_header("Authorization", "Discogs token=%s" % self.token)
        while True:
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429:           # rate limited: wait and retry
                    time.sleep(60)
                    continue
                raise

    # --- cache on disk ---
    def _load_cache(self):
        try:
            with open(self.coll_file) as f:
                self.releases = json.load(f)
        except (OSError, ValueError):
            pass
        try:
            with open(self.tl_file) as f:
                self.tracklists = {int(k): v for k, v in json.load(f).items()}
        except (OSError, ValueError):
            pass
        try:
            with open(self.price_file) as f:
                self.prices = {int(k): v for k, v in json.load(f).items()}
        except (OSError, ValueError):
            pass

    def _save(self, path, data):
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)

    # --- background workers ---
    def _collection_loop(self):
        while True:
            try:
                releases, page, pages = [], 1, 1
                while page <= pages:
                    data = self._get(
                        "https://api.discogs.com/users/%s/collection/folders/0/releases"
                        "?per_page=100&page=%d" % (self.user, page))
                    pages = data.get("pagination", {}).get("pages", 1)
                    for item in data.get("releases", []):
                        b = item.get("basic_information", {})
                        fmt = ""
                        if b.get("formats"):
                            f0 = b["formats"][0]
                            parts = [f0.get("name", "")] + (f0.get("descriptions") or [])
                            fmt = ", ".join(p for p in parts if p)
                        releases.append({
                            "id": b.get("id"),
                            "added": item.get("date_added", ""),
                            "title": b.get("title", ""),
                            "year": b.get("year") or "",
                            "format": fmt,
                            "artists": [clean_artist(a.get("name")) for a in b.get("artists", [])],
                        })
                    page += 1
                    time.sleep(1.5)
                with self.lock:
                    self.releases = releases
                self._save(self.coll_file, releases)
                self.error = ""
                self.last_sync = time.strftime("%Y-%m-%d %H:%M:%S")
                print("Discogs: loaded %d releases" % len(releases), flush=True)
                time.sleep(COLLECTION_REFRESH_HOURS * 3600)
            except Exception as e:
                self.error = "Collection: %s" % e
                print("Discogs error: %s" % self.error, flush=True)
                time.sleep(300)             # retry in 5 minutes

    def _tracklist_loop(self):
        delay = 1.2 if self.token else 2.6   # stay under Discogs' rate limit
        while True:
            rid = None
            price_rid = None
            buy_item = None
            with self.lock:
                if self.queue:
                    rid = self.queue.pop(0)
                elif self.price_queue:
                    price_rid = self.price_queue.pop(0)
                elif self.buy_queue:
                    buy_item = self.buy_queue.pop(0)
            if price_rid is not None:
                self._fetch_prices(price_rid, delay)
                continue
            if buy_item is not None:
                self._fetch_buy(buy_item, delay)
                continue
            if rid is None or rid in self.tracklists:
                time.sleep(1)
                continue
            try:
                data = self._get("https://api.discogs.com/releases/%d" % rid)
                titles = [norm(t.get("title")) for t in data.get("tracklist", [])
                          if t.get("type_", "track") == "track"]
                with self.lock:
                    self.tracklists[rid] = titles
                    snapshot = dict(self.tracklists)
                self._save(self.tl_file, snapshot)
            except Exception as e:
                self.error = "Tracklist %s: %s" % (rid, e)
                print("Discogs error: %s" % self.error, flush=True)
            time.sleep(delay)

    def _fetch_prices(self, rid, delay):
        info = {"t": time.time(), "lowest": "", "for_sale": None, "vgplus": ""}
        try:
            data = self._get("https://api.discogs.com/marketplace/stats/%d?curr_abbr=%s" % (rid, CURRENCY))
            info["lowest"] = money(data.get("lowest_price"))
            info["for_sale"] = data.get("num_for_sale")
        except Exception as e:
            self.error = "Prices %s: %s" % (rid, e)
        time.sleep(delay)
        if self.token:
            try:
                sug = self._get("https://api.discogs.com/marketplace/price_suggestions/%d" % rid)
                info["vgplus"] = money(sug.get("Very Good Plus (VG+)"))
            except Exception:
                pass                        # needs seller settings on Discogs
            time.sleep(delay)
        with self.lock:
            self.prices[rid] = info
            snapshot = dict(self.prices)
        self._save(self.price_file, snapshot)

    def _fetch_buy(self, item, delay):
        """Find vinyl pressings of an album you don't own and their lowest price."""
        key, artist, album = item
        info = {"t": time.time(), "found": False, "lowest": "", "for_sale": 0}
        try:
            params = urllib.parse.urlencode({
                "type": "release", "format": "Vinyl", "artist": artist,
                "release_title": clean_title(album), "per_page": 5})
            results = self._get("https://api.discogs.com/database/search?" + params).get("results", [])
            time.sleep(delay)
            best = None
            for r in results[:3]:
                stats = self._get("https://api.discogs.com/marketplace/stats/%d?curr_abbr=%s"
                                  % (r["id"], CURRENCY))
                time.sleep(delay)
                info["found"] = True
                info["for_sale"] += stats.get("num_for_sale") or 0
                lp = stats.get("lowest_price")
                if lp and lp.get("value") is not None and (best is None or lp["value"] < best["value"]):
                    best = lp
            if results:
                info["found"] = True
            info["lowest"] = money(best)
        except Exception as e:
            self.error = "Cost to buy: %s" % e
        with self.lock:
            self.buy[key] = info

    def _buy_text(self, artist, album):
        key = norm(artist) + "|" + norm(clean_title(album))
        info = self.buy.get(key)
        stale = not info or time.time() - info.get("t", 0) > PRICE_REFRESH_HOURS * 3600
        if stale and not any(q[0] == key for q in self.buy_queue):
            self.buy_queue.append((key, artist, album))
        if not info:
            return "Checking prices..."
        if not info["found"]:
            return "No vinyl pressing found on Discogs"
        if info["lowest"]:
            return "Est. cost from %s \u00b7 %d for sale" % (info["lowest"], info["for_sale"])
        return "None for sale right now"

    def _price_text(self, rid):
        """Return a price line for a release, queueing a refresh if needed."""
        info = self.prices.get(rid)
        stale = not info or time.time() - info.get("t", 0) > PRICE_REFRESH_HOURS * 3600
        if stale and rid not in self.price_queue:
            self.price_queue.append(rid)
        if not info:
            return "Checking prices..."
        parts = []
        if info.get("vgplus"):
            parts.append("VG+ value %s" % info["vgplus"])
        if info.get("lowest"):
            parts.append("lowest listed %s" % info["lowest"])
        if info.get("for_sale") is not None:
            parts.append("%d for sale" % info["for_sale"])
        text = " \u00b7 ".join(parts)
        return text[:1].upper() + text[1:] if text else "No copies for sale"

    def debug(self):
        with self.lock:
            return {
                "user": self.user,
                "token_set": bool(self.token),
                "releases_loaded": len(self.releases),
                "tracklists_cached": len(self.tracklists),
                "tracklists_queued": len(self.queue),
                "last_sync": self.last_sync,
                "error": self.error,
                "config_file": os.path.join(HERE, "config.json"),
                "sample": [r["title"] + " - " + ", ".join(r["artists"]) for r in self.releases[:5]],
            }

    # --- matching ---
    def lookup(self, artist, album, title):
        if not self.user:
            return None
        a, al, t = norm(artist), norm(album), norm(title)
        with self.lock:
            by_artist = [r for r in self.releases
                         if any(contains_words(a, norm(n)) or contains_words(norm(n), a)
                                for n in r["artists"])]
            if not by_artist:
                if not album:
                    return {"level": "none", "text": ""}
                return {"level": "notowned", "label": "Not owned on vinyl",
                        "text": self._buy_text(artist, album), "price": ""}

            # Ask the worker to fetch tracklists we don't have yet
            for r in by_artist:
                if r["id"] not in self.tracklists and r["id"] not in self.queue:
                    self.queue.append(r["id"])

            track_hits = [r for r in by_artist if t and t in self.tracklists.get(r["id"], [])]
            album_hits = [r for r in by_artist if al and norm(r["title"]) == al]
            pending = any(r["id"] not in self.tracklists for r in by_artist)
            first = (track_hits or album_hits or [None])[0]
            price = self._price_text(first["id"]) if first else ""

        def describe(r):
            bits = [str(b) for b in (r["year"], r["format"]) if b]
            text = "%s (%s)" % (r["title"], ", ".join(bits)) if bits else r["title"]
            added = format_added(r.get("added"))
            if added:
                text += " \u00b7 added %s" % added
            return text

        hits = track_hits or album_hits
        if hits:
            level = "track" if track_hits else "album"
            label = "Owned on vinyl"
            text = "; ".join(describe(r) for r in hits[:2])
            if len(hits) > 2:
                text += " + %d more" % (len(hits) - 2)
            return {"level": level, "label": label, "text": text, "price": price}

        n = len(by_artist)
        if pending:
            return {"level": "artist", "label": "Checking your vinyl",
                    "text": "%d record%s by this artist..." % (n, "" if n == 1 else "s")}
        if not album:
            return {"level": "artist", "label": "On your vinyl",
                    "text": "%d record%s by this artist" % (n, "" if n == 1 else "s")}
        with self.lock:
            buy = self._buy_text(artist, album)
        return {"level": "notowned", "label": "Not owned on vinyl", "text": buy,
                "price": "You own %d other record%s by this artist" % (n, "" if n == 1 else "s")}


DISCOGS = Discogs(DISCOGS_USER, DISCOGS_TOKEN)


# ---------------- Last.fm play counts ----------------

def clean_title(text):
    """Strip '(2019 Remaster)', '- Remastered' etc. but keep the original case."""
    s = text or ""
    s = re.sub(r"\s*[\(\[][^\)\]]*" + REMASTER_WORDS + r"[^\)\]]*[\)\]]", "", s, flags=re.I)
    s = re.sub(r"\s+-\s+[^-]*" + REMASTER_WORDS + r".*$", "", s, flags=re.I)
    return s.strip()


MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


def month_year(uts):
    t = time.localtime(uts)
    return "%s %d" % (MONTH_NAMES[t.tm_mon - 1], t.tm_year)


def time_ago(uts):
    secs = max(0, time.time() - uts)
    for limit, size, unit in [(3600, 60, "minute"), (86400, 3600, "hour"),
                              (86400 * 14, 86400, "day"), (86400 * 60, 86400 * 7, "week"),
                              (86400 * 730, 86400 * 30.44, "month")]:
        if secs < limit:
            n = max(1, int(secs // size))
            return "%d %s%s ago" % (n, unit, "" if n == 1 else "s")
    n = max(2, int(round(secs / (86400 * 365.25))))
    return "%d years ago" % n


class LastFM:
    def __init__(self, user, key):
        self.user = user
        self.key = key
        self.lock = threading.Lock()
        self.cache = {}                     # (artist, album, title) -> {"t": time, "data": {...}}
        self.queue = []
        self.error = ""
        if user and key:
            threading.Thread(target=self._loop, daemon=True).start()

    def _call(self, method, **params):
        params.update({"method": method, "api_key": self.key, "username": self.user,
                       "autocorrect": 1, "format": "json"})
        url = "https://ws.audioscrobbler.com/2.0/?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "VolumioNowPlaying/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def _count(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _fetch(self, artist, album, title):
        data = {"track": 0, "loved": False, "artist": 0, "album": 0, "first": None, "last": None}
        matched = title
        # Track: try the title as-is, then without remaster/edition tags
        for t in [title, clean_title(title)]:
            try:
                tr = self._call("track.getInfo", artist=artist, track=t).get("track", {})
                data["track"] = self._count(tr.get("userplaycount"))
                data["loved"] = str(tr.get("userloved")) == "1"
                if data["track"]:
                    matched = tr.get("name") or t
                    artist_name = (tr.get("artist") or {}).get("name")
                    if artist_name:
                        artist = artist_name
                    break
            except Exception as e:
                self.error = "track.getInfo: %s" % e
            if clean_title(title) == title:
                break
        if data["track"]:
            data["first"], data["last"] = self._history(artist, matched)
        try:
            ar = self._call("artist.getInfo", artist=artist).get("artist", {})
            data["artist"] = self._count(ar.get("stats", {}).get("userplaycount"))
        except Exception as e:
            self.error = "artist.getInfo: %s" % e
        if album:
            for a in [album, clean_title(album)]:
                try:
                    al = self._call("album.getInfo", artist=artist, album=a).get("album", {})
                    data["album"] = self._count(al.get("userplaycount"))
                    if data["album"]:
                        break
                except Exception as e:
                    self.error = "album.getInfo: %s" % e
                if clean_title(album) == album:
                    break
        return data

    def _scrobble_page(self, artist, track, page):
        """One scrobble of this track: page 1 is the newest."""
        res = self._call("user.getTrackScrobbles", user=self.user, artist=artist,
                         track=track, limit=1, page=page).get("trackscrobbles", {})
        items = res.get("track") or []
        if isinstance(items, dict):
            items = [items]
        total = self._count(res.get("@attr", {}).get("totalPages"))
        uts = None
        for it in items:
            d = it.get("date") or {}
            if d.get("uts"):
                uts = int(d["uts"])
        return uts, total

    def _history(self, artist, track):
        """Return (first scrobble, last scrobble before this play) as Unix times."""
        try:
            newest, total = self._scrobble_page(artist, track, 1)
            if not newest or not total:
                return None, None
            first = newest if total == 1 else self._scrobble_page(artist, track, total)[0]
            last = newest
            # If the newest scrobble is this play, use the one before it
            if time.time() - newest < 20 * 60:
                last = self._scrobble_page(artist, track, 2)[0] if total > 1 else None
            return first, last
        except Exception as e:
            self.error = "user.getTrackScrobbles: %s" % e
            return None, None

    def _loop(self):
        while True:
            item = None
            with self.lock:
                if self.queue:
                    item = self.queue.pop(0)
            if item is None:
                time.sleep(0.5)
                continue
            self.error = ""
            data = self._fetch(*item)
            if self.error and not any([data["track"], data["artist"], data["album"]]):
                print("Last.fm error: %s" % self.error, flush=True)
                data = None                 # don't show zeros when Last.fm failed
            with self.lock:
                self.cache[item] = {"t": time.time(), "data": data}

    def lookup(self, artist, album, title):
        if not (self.user and self.key and artist and title):
            return None
        key = (artist, album or "", title)
        with self.lock:
            entry = self.cache.get(key)
            stale = not entry or time.time() - entry["t"] > LASTFM_REFRESH_MINUTES * 60
            if stale and key not in self.queue:
                self.queue.append(key)
        if not entry:
            return {"text": "Checking scrobbles..."}
        d = entry["data"]
        if d is None:
            return None

        def plays(n):
            return "%s play%s" % ("{:,}".format(n), "" if n == 1 else "s")

        parts = []
        parts.append(plays(d["track"]) + " of this track" if d["track"] else "First play of this track")
        if d["album"]:
            parts.append(plays(d["album"]) + " of the album")
        if d["artist"]:
            parts.append(plays(d["artist"]) + " of " + artist)
        history = []
        if d.get("first"):
            history.append("First scrobbled " + month_year(d["first"]))
        if d.get("last"):
            history.append("last played " + time_ago(d["last"]))
        hist = " \u00b7 ".join(history)
        return {"text": " \u00b7 ".join(parts), "loved": d["loved"],
                "history": hist[:1].upper() + hist[1:]}


LASTFM = LastFM(LASTFM_USER, LASTFM_KEY)


# ---------------- LG TV keep-alive ----------------
# Stops the LG webOS screen-saver by sending the TV a tiny input every minute,
# the same way phone remote apps do. The TV's address is picked up
# automatically from the TV browser that has the page open.

TV_ENABLED = CONFIG.get("tv_keepalive", True)
TV_FIXED_IP = CONFIG.get("tv_ip", "")
TV_INPUT = CONFIG.get("tv_keepalive_input", "move")    # "move" or a button name such as "BLUE"
TV_ONLY_PLAYING = CONFIG.get("tv_keepalive_only_when_playing", True)
TV_INTERVAL = 60                                       # seconds between nudges
TV_KEY_FILE = os.path.join(HERE, "lgtv_key.json")

TV_MANIFEST = {
    "manifestVersion": 1,
    "appVersion": "1.0",
    "signed": {
        "appId": "com.volumio.nowplaying",
        "vendorId": "com.volumio",
        "localizedAppNames": {"": "Volumio now playing"},
        "localizedVendorNames": {"": "Volumio now playing"},
        "permissions": ["CONTROL_INPUT_JOYSTICK", "CONTROL_MOUSE_AND_KEYBOARD"],
        "serial": "volumio-nowplaying",
    },
    "permissions": ["CONTROL_INPUT_JOYSTICK", "CONTROL_MOUSE_AND_KEYBOARD"],
    "signatures": [],
}


class WebSocket:
    """A minimal WebSocket client (text frames only), using the standard library."""

    def __init__(self, url, timeout=10):
        u = urllib.parse.urlparse(url)
        secure = u.scheme == "wss"
        port = u.port or (443 if secure else 80)
        raw = socket.create_connection((u.hostname, port), timeout=timeout)
        if secure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE     # LG TVs use a self-signed certificate
            raw = ctx.wrap_socket(raw, server_hostname=u.hostname)
        self.sock = raw
        key = base64.b64encode(os.urandom(16)).decode()
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, u.hostname, port, key))
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise IOError("connection closed during handshake")
            head += chunk
        status_line = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status_line:
            raise IOError("handshake failed: %s" % status_line.decode(errors="replace"))
        self.buf = head.split(b"\r\n\r\n", 1)[1]

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise IOError("connection closed")
            self.buf += chunk
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def send(self, text, opcode=0x1):
        payload = text.encode("utf-8") if isinstance(text, str) else text
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += n.to_bytes(2, "big")
        else:
            header.append(0x80 | 127)
            header += n.to_bytes(8, "big")
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv(self):
        while True:
            b1, b2 = self._read(2)
            opcode = b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = int.from_bytes(self._read(2), "big")
            elif n == 127:
                n = int.from_bytes(self._read(8), "big")
            mask = self._read(4) if b2 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x9:                       # ping -> pong
                self.send(data, opcode=0xA)
                continue
            if opcode == 0x8:
                raise IOError("connection closed by TV")
            if opcode in (0x1, 0x0):
                return data.decode("utf-8", errors="replace")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


class LGTV:
    def __init__(self):
        self.lock = threading.Lock()
        self.ip = TV_FIXED_IP
        self.last_seen = 0          # when the TV browser last polled the page
        self.status = "Waiting for the TV to open the page"
        self.last_ok = ""
        self.error = ""
        self.key = ""
        try:
            with open(TV_KEY_FILE) as f:
                self.key = json.load(f).get("client_key", "")
        except (OSError, ValueError):
            pass
        if TV_ENABLED:
            threading.Thread(target=self._loop, daemon=True).start()

    def seen(self, ip, user_agent):
        """Called for every page poll; remembers the TV if it's an LG browser."""
        ua = (user_agent or "").lower()
        if "web0s" in ua or "webos" in ua or "smarttv" in ua:
            with self.lock:
                if not TV_FIXED_IP:
                    self.ip = ip
                self.last_seen = time.time()

    def _connect(self):
        """Open the control connection and register (pairing the first time)."""
        last_error = None
        for url in ("wss://%s:3001/" % self.ip, "ws://%s:3000/" % self.ip):
            try:
                ws = WebSocket(url)
            except Exception as e:
                last_error = e
                continue
            payload = {"forcePairing": False, "pairingType": "PROMPT", "manifest": TV_MANIFEST}
            if self.key:
                payload["client-key"] = self.key
            ws.send(json.dumps({"type": "register", "id": "register_0", "payload": payload}))
            deadline = time.time() + 60
            ws.sock.settimeout(65)
            while time.time() < deadline:
                msg = json.loads(ws.recv())
                if msg.get("type") == "registered":
                    new_key = (msg.get("payload") or {}).get("client-key")
                    if new_key and new_key != self.key:
                        self.key = new_key
                        with open(TV_KEY_FILE, "w") as f:
                            json.dump({"client_key": new_key}, f)
                        print("LG TV: paired", flush=True)
                    ws.sock.settimeout(10)
                    return ws, url
                if msg.get("type") == "response" and (msg.get("payload") or {}).get("pairingType"):
                    self.status = "Accept the connection request on the TV"
                    print("LG TV: waiting for you to accept the prompt on the TV", flush=True)
                if msg.get("type") == "error":
                    ws.close()
                    raise IOError("TV refused: %s" % msg.get("error"))
            ws.close()
            raise IOError("pairing prompt was not accepted in time")
        raise IOError("could not connect to the TV: %s" % last_error)

    def nudge(self):
        ws, url = self._connect()
        pointer = None
        try:
            ws.send(json.dumps({"type": "request", "id": "pointer_1",
                                "uri": "ssap://com.webos.service.networkinput/getPointerInputSocket"}))
            path = None
            for _ in range(5):
                msg = json.loads(ws.recv())
                if msg.get("id") == "pointer_1":
                    path = (msg.get("payload") or {}).get("socketPath")
                    if not path:
                        raise IOError("TV did not allow remote input: %s" % (msg.get("error") or msg.get("payload")))
                    break
            if not path:
                raise IOError("no reply from the TV")
            pointer = WebSocket(path)
            if TV_INPUT == "move":
                # A one-pixel nudge there and back: resets the idle timer
                pointer.send("type:move\ndx:1\ndy:0\ndown:0\n\n")
                time.sleep(0.2)
                pointer.send("type:move\ndx:-1\ndy:0\ndown:0\n\n")
            else:
                pointer.send("type:button\nname:%s\n\n" % TV_INPUT)
        finally:
            if pointer:
                pointer.close()
            ws.close()

    def _loop(self):
        while True:
            time.sleep(TV_INTERVAL)
            with self.lock:
                ip, seen = self.ip, self.last_seen
            if not ip:
                continue
            if time.time() - seen > 3 * REFRESH_SECONDS + 10:
                self.status = "TV page not open"
                continue
            if TV_ONLY_PLAYING and PLAYER.get("status") != "play":
                self.status = "Paused, letting the screen-saver run"
                continue
            try:
                self.nudge()
                self.status = "Keeping the TV awake"
                self.last_ok = time.strftime("%H:%M:%S")
                self.error = ""
            except Exception as e:
                self.error = str(e)
                self.status = "Error"
                print("LG TV error: %s" % e, flush=True)

    def debug(self):
        return {
            "enabled": TV_ENABLED,
            "tv_ip": self.ip,
            "paired": bool(self.key),
            "status": self.status,
            "last_nudge": self.last_ok,
            "error": self.error,
            "input": TV_INPUT,
            "only_when_playing": TV_ONLY_PLAYING,
        }


PLAYER = {"status": ""}
TV = LGTV()


# ---------------- Queue and album art proxy ----------------

ART = {"url": "", "bytes": b"", "type": "image/jpeg"}
ART_LOCK = threading.Lock()


def volumio_json(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def up_next(state, count=2):
    """Return the next tracks in Volumio's queue."""
    if state.get("random"):
        return {"shuffle": True, "tracks": []}
    try:
        queue = volumio_json(VOLUMIO_QUEUE).get("queue", [])
    except Exception:
        return {"shuffle": False, "tracks": []}
    pos = state.get("position")
    if not isinstance(pos, int):
        return {"shuffle": False, "tracks": []}
    upcoming = queue[pos + 1:pos + 1 + count]
    if state.get("repeat") and len(upcoming) < count:
        upcoming += queue[:count - len(upcoming)]
    return {"shuffle": False, "tracks": [
        {"title": t.get("name") or t.get("title") or "", "artist": t.get("artist") or ""}
        for t in upcoming]}


def get_art():
    """Fetch the current album art so the page can read its colours."""
    with ART_LOCK:
        url, cached, ctype = ART["url"], ART["bytes"], ART["type"]
    if not url:
        return None, None
    if cached:
        return cached, ctype
    req = urllib.request.Request(url, headers={"User-Agent": "VolumioNowPlaying/1.0"})
    with urllib.request.urlopen(req, timeout=5) as r:
        data = r.read()
        ctype = r.headers.get("Content-Type") or "image/jpeg"
    with ART_LOCK:
        if ART["url"] == url:
            ART["bytes"], ART["type"] = data, ctype
    return data, ctype



def get_status(host):
    status = {"ok": True}
    try:
        with urllib.request.urlopen(VOLUMIO_API, timeout=3) as r:
            state = json.loads(r.read().decode("utf-8"))
    except Exception:
        return {"ok": False, "error": "Could not reach Volumio"}

    art = state.get("albumart") or ""
    if art.startswith("/"):
        art = "http://localhost:3000%s" % art
    with ART_LOCK:
        if art != ART["url"]:
            ART.update({"url": art, "bytes": b"", "type": "image/jpeg"})
    # The page loads the art through this server, so it can read its colours
    art_page = "/api/art?v=%d" % (abs(hash(art)) % 100000000) if art else ""

    src_khz = parse_number(state.get("samplerate"))
    src_depth = parse_number(state.get("bitdepth"))
    dac = read_dac()

    match = None
    if dac and src_khz and dac["rate_khz"] is not None:
        match = abs(dac["rate_khz"] - src_khz) < 0.05 and (
            not src_depth or not dac["depth"] or int(src_depth) == dac["depth"]
        )

    PLAYER["status"] = state.get("status") or ""
    status.update({
        "status": state.get("status"),
        "title": state.get("title") or "",
        "artist": state.get("artist") or "",
        "album": state.get("album") or "",
        "albumart": art_page,
        "upnext": up_next(state),
        "seek": state.get("seek") or 0,             # milliseconds
        "duration": state.get("duration") or 0,     # seconds
        "service": state.get("service") or "",
        "source": {
            "label": "%s kHz / %s-bit" % (fmt_khz(src_khz), int(src_depth) if src_depth else "?")
            if src_khz else (state.get("samplerate") or ""),
        },
        "dac": dac,
        "bitperfect": match,
        "vinyl": DISCOGS.lookup(state.get("artist"), state.get("album"), state.get("title")),
        "lastfm": LASTFM.lookup(state.get("artist"), state.get("album"), state.get("title")),
        "refresh": REFRESH_SECONDS,
    })
    return status


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Now playing</title>
<style>
  html { background: #0b0b0d; }
  :root { --accent: #9fb4ff; }
  html, body { margin: 0; height: 100%; color: #f2f2f2;
    font-family: "Segoe UI", Roboto, Helvetica, Arial, sans-serif; overflow: hidden; }
  #bg { position: fixed; inset: 0; top: 0; left: 0; right: 0; bottom: 0;
    background-size: cover; background-position: center;
    filter: blur(60px) brightness(0.35); transform: scale(1.2); transition: background-image 1s;
    -webkit-animation: drift 90s ease-in-out infinite alternate;
    animation: drift 90s ease-in-out infinite alternate; }
  @-webkit-keyframes drift {
    0%   { -webkit-transform: scale(1.2) translate(0, 0) rotate(0deg); }
    50%  { -webkit-transform: scale(1.35) translate(-3%, 2%) rotate(3deg); }
    100% { -webkit-transform: scale(1.25) translate(3%, -2%) rotate(-2deg); }
  }
  @keyframes drift {
    0%   { transform: scale(1.2) translate(0, 0) rotate(0deg); }
    50%  { transform: scale(1.35) translate(-3%, 2%) rotate(3deg); }
    100% { transform: scale(1.25) translate(3%, -2%) rotate(-2deg); }
  }
  #wrap { position: relative; display: flex; align-items: center; height: 100%;
    padding: 0 6vw; box-sizing: border-box; transition: transform 20s ease-in-out; }
  #keepawake { position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    object-fit: cover; z-index: -1; background: #000; }
  #art { width: 38vw; max-width: 72vh; height: 38vw; max-height: 72vh; flex: none;
    border-radius: 1.2vw; background: #222 center / cover no-repeat;
    box-shadow: 0 2vw 5vw rgba(0,0,0,0.6), 0 0 6vw -1vw var(--accent);
    transition: box-shadow 1.5s; }
  #info { margin-left: 5vw; min-width: 0; }
  #title { font-size: 4.2vw; font-weight: 700; line-height: 1.1; margin: 0 0 1vw;
    max-width: 48vw; overflow: hidden; display: -webkit-box;
    -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
  #artist { font-size: 2.6vw; opacity: 0.9; margin: 0 0 0.4vw; }
  #album { font-size: 1.9vw; opacity: 0.6; margin: 0 0 3vw; }
  .row { display: flex; align-items: baseline; font-size: 1.7vw; margin: 0.5vw 0; }
  .label { width: 14vw; opacity: 0.8; flex: none; color: var(--accent); transition: color 1.5s; }
  #progress { display: flex; align-items: center; margin: 0 0 2.2vw; font-size: 1.3vw;
    font-variant-numeric: tabular-nums; }
  #track { position: relative; width: 30vw; height: 0.45vw; border-radius: 1vw;
    background: rgba(255,255,255,0.15); margin: 0 1.2vw; overflow: hidden; }
  #fill { position: absolute; left: 0; top: 0; bottom: 0; width: 0; border-radius: 1vw;
    background: var(--accent); transition: background 1.5s; }
  #elapsed, #remaining { opacity: 0.7; min-width: 5vw; }
  #remaining { text-align: left; }
  #elapsed { text-align: right; }
  #upnext { position: fixed; left: 6vw; right: 6vw; bottom: 4vh; font-size: 1.4vw;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; opacity: 0.75; }
  #upnext .ulabel { color: var(--accent); font-weight: 600; margin-right: 1vw;
    text-transform: uppercase; letter-spacing: 0.15vw; font-size: 1.1vw; transition: color 1.5s; }
  #upnext .sep { opacity: 0.4; margin: 0 1vw; }
  #badge { display: inline-block; margin-top: 2.5vw; padding: 0.7vw 1.6vw; border-radius: 3vw;
    font-size: 1.6vw; font-weight: 600; }
  .good { background: rgba(0,200,90,0.2); color: #5cf09a; }
  .bad  { background: rgba(255,90,60,0.2); color: #ff8a70; }
  .idle { background: rgba(255,255,255,0.1); color: #bbb; }
  #led { display: inline-block; width: 1.3vw; height: 1.3vw; border-radius: 50%;
    margin-right: 0.8vw; vertical-align: middle; box-shadow: 0 0 1vw currentColor; }
  #note { font-size: 1.1vw; opacity: 0.4; margin-top: 0.6vw; }
  #vinyl { display: none; margin-top: 1.6vw; font-size: 1.5vw; max-width: 48vw; }
  #vinyl .vlabel { display: inline-block; padding: 0.5vw 1.2vw; border-radius: 3vw; font-weight: 600;
    background: rgba(170,120,255,0.22); color: #cdb2ff; margin-right: 1vw; }
  #vinyl.artist .vlabel { background: rgba(255,255,255,0.1); color: #ccc; }
  #vinyl.notowned .vlabel { background: rgba(255,160,50,0.2); color: #ffc27a; }
  #vinyl .vtext { opacity: 0.85; }
  #lastfm { display: none; margin-top: 1.2vw; font-size: 1.5vw; max-width: 48vw; }
  #lastfm .llabel { display: inline-block; padding: 0.5vw 1.2vw; border-radius: 3vw; font-weight: 600;
    background: rgba(213,16,7,0.25); color: #ff8a80; margin-right: 1vw; }
  #lastfm .ltext { opacity: 0.85; }
  #lhist { display: block; margin-top: 0.7vw; font-size: 1.3vw; opacity: 0.6; }
  #vprice { display: block; margin-top: 0.7vw; font-size: 1.3vw; opacity: 0.6; }
  .ellipsis { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 45vw; }
</style>
</head>
<body>
<div id="bg"></div>
<div id="upnext"></div>
<div id="wrap">
  <div id="art"></div>
  <div id="info">
    <div id="title">Loading...</div>
    <div id="artist" class="ellipsis"></div>
    <div id="album" class="ellipsis"></div>
    <div id="progress"><span id="elapsed">0:00</span><div id="track"><div id="fill"></div></div><span id="remaining"></span></div>
    <div class="row"><span class="label">Source</span><span id="src"></span></div>
    <div class="row"><span class="label">To DAC</span><span id="dac"></span></div>
    <div class="row"><span class="label">Zen LED</span><span><span id="led"></span><span id="ledname"></span></span></div>
    <div id="note">Your 'c' firmware upsamples, so the real LED shows white.</div>
    <div id="badge" class="idle"></div>
    <div id="vinyl"><span class="vlabel" id="vlabel"></span><span class="vtext" id="vtext"></span><span id="vprice"></span></div>
    <div id="lastfm"><span class="llabel" id="llabel">Last.fm</span><span class="ltext" id="ltext"></span><span id="lhist"></span></div>
  </div>
</div>
<script>
var lastArt = null;
var pollTimer = null;
var refresh = 5;

function setText(id, text) { document.getElementById(id).textContent = text; }

// ---------- Accent colour from the album art ----------
function setAccent(url) {
  if (!url) { document.documentElement.style.setProperty('--accent', '#9fb4ff'); return; }
  var img = new Image();
  img.onload = function () {
    try {
      var c = document.createElement('canvas');
      c.width = c.height = 32;
      var ctx = c.getContext('2d');
      ctx.drawImage(img, 0, 0, 32, 32);
      var d = ctx.getImageData(0, 0, 32, 32).data;
      var buckets = {};
      for (var i = 0; i < d.length; i += 4) {
        var r = d[i], g = d[i + 1], b = d[i + 2];
        var max = Math.max(r, g, b), min = Math.min(r, g, b);
        var sat = max === 0 ? 0 : (max - min) / max;
        if (max < 40 || (min > 225)) { continue; }          // skip near-black and near-white
        var key = (r >> 5) + ',' + (g >> 5) + ',' + (b >> 5);
        var w = 0.2 + sat * sat * 3;                          // favour colourful pixels
        if (!buckets[key]) { buckets[key] = { w: 0, r: 0, g: 0, b: 0 }; }
        var k = buckets[key];
        k.w += w; k.r += r * w; k.g += g * w; k.b += b * w;
      }
      var best = null;
      for (var key2 in buckets) {
        if (!best || buckets[key2].w > best.w) { best = buckets[key2]; }
      }
      if (!best) { return; }
      var hsl = rgbToHsl(best.r / best.w, best.g / best.w, best.b / best.w);
      // Keep it readable on the dark background
      var l = Math.max(hsl[2], 0.62), sAdj = Math.max(hsl[1], 0.45);
      document.documentElement.style.setProperty('--accent',
        'hsl(' + Math.round(hsl[0] * 360) + ',' + Math.round(sAdj * 100) + '%,' + Math.round(l * 100) + '%)');
    } catch (e) { /* leave the current accent */ }
  };
  img.src = url;
}

function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  var max = Math.max(r, g, b), min = Math.min(r, g, b), h = 0, s2 = 0, l = (max + min) / 2;
  if (max !== min) {
    var d = max - min;
    s2 = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) { h = (g - b) / d + (g < b ? 6 : 0); }
    else if (max === g) { h = (b - r) / d + 2; }
    else { h = (r - g) / d + 4; }
    h /= 6;
  }
  return [h, s2, l];
}

// ---------- Progress bar ----------
// Keeps its own clock and only re-syncs to Volumio when the track changes,
// playback pauses/resumes, or Volumio's position is clearly different
// (e.g. after skipping within the track). This stops it jumping back when
// Volumio reports a position that hasn't been updated yet.
var pos = { key: '', start: 0, duration: 0, playing: false, pausedAt: 0, lastReported: -1 };

function fmtTime(sec) {
  sec = Math.max(0, Math.floor(sec));
  var m = Math.floor(sec / 60), s2 = sec % 60;
  return m + ':' + (s2 < 10 ? '0' : '') + s2;
}

function elapsedNow() {
  if (!pos.duration) { return 0; }
  var el = pos.playing ? (Date.now() - pos.start) / 1000 : pos.pausedAt;
  return Math.min(Math.max(el, 0), pos.duration);
}

function syncProgress(s) {
  var key = (s.artist || '') + '|' + (s.album || '') + '|' + (s.title || '');
  var playing = s.status === 'play';
  var reported = (s.seek || 0) / 1000;
  var trackChanged = key !== pos.key;
  var stateChanged = playing !== pos.playing;
  // Only trust a new position if Volumio's value has actually moved;
  // an unchanged value just means it hasn't been updated yet.
  var reportMoved = reported !== pos.lastReported;
  var drift = Math.abs(elapsedNow() - reported);
  pos.lastReported = reported;

  if (trackChanged || stateChanged || (reportMoved && drift > 4)) {
    pos.key = key;
    pos.start = Date.now() - reported * 1000;
    pos.pausedAt = reported;
  }
  pos.duration = s.duration || 0;
  pos.playing = playing;
}

function drawProgress() {
  var prog = document.getElementById('progress');
  if (!pos.duration) { prog.style.visibility = 'hidden'; return; }
  prog.style.visibility = 'visible';
  var el = elapsedNow();
  document.getElementById('fill').style.width = (el / pos.duration * 100) + '%';
  setText('elapsed', fmtTime(el));
  setText('remaining', fmtTime(pos.duration));   // total length, like the Tidal app
}
setInterval(drawProgress, 500);


// Shrink the title until it fits on at most two lines
var lastTitle = null;
function fitTitle() {
  var el = document.getElementById('title');
  var vw = window.innerWidth / 100;
  var size = 4.2;
  el.style.webkitLineClamp = 'unset';
  el.style.fontSize = size + 'vw';
  while (size > 2.4 && el.scrollHeight > size * vw * 1.1 * 2 + 2) {
    size -= 0.2;
    el.style.fontSize = size + 'vw';
  }
  el.style.webkitLineClamp = '2';
}
window.addEventListener('resize', fitTitle);

function update() {
  fetch('/api/status', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (s) {
      if (!s.ok) { lastTitle = null; setText('title', s.error || 'Error'); return; }
      refresh = s.refresh || refresh;
      var title = s.title || (s.status === 'play' ? '' : 'Nothing playing');
      if (title !== lastTitle) { lastTitle = title; setText('title', title); fitTitle(); }
      setText('artist', s.artist);
      setText('album', s.album);
      setText('src', s.source && s.source.label ? s.source.label : '-');

      var led = document.getElementById('led');
      if (s.dac) {
        setText('dac', s.dac.label);
        led.style.background = s.dac.led.hex;
        led.style.color = s.dac.led.hex;
        setText('ledname', s.dac.led.name + ' (' + s.dac.led.desc + ')');
      } else {
        setText('dac', 'Idle');
        led.style.background = '#444';
        led.style.color = 'transparent';
        setText('ledname', '-');
      }

      var badge = document.getElementById('badge');
      if (s.bitperfect === true) { badge.className = 'good'; badge.textContent = 'Bit-perfect'; }
      else if (s.bitperfect === false) { badge.className = 'bad'; badge.textContent = 'Being resampled'; }
      else { badge.className = 'idle'; badge.textContent = s.dac ? 'Checking...' : 'Not playing'; }

      var vinyl = document.getElementById('vinyl');
      if (s.vinyl && s.vinyl.level && s.vinyl.level !== 'none') {
        vinyl.style.display = 'block';
        vinyl.className = s.vinyl.level;
        setText('vlabel', s.vinyl.label);
        setText('vtext', s.vinyl.text);
        setText('vprice', s.vinyl.price || '');
      } else {
        vinyl.style.display = 'none';
      }

      var lf = document.getElementById('lastfm');
      if (s.lastfm && s.lastfm.text) {
        lf.style.display = 'block';
        setText('llabel', s.lastfm.loved ? 'Last.fm \u2665' : 'Last.fm');
        setText('ltext', s.lastfm.text);
        setText('lhist', s.lastfm.history || '');
      } else {
        lf.style.display = 'none';
      }

      syncProgress(s);
      drawProgress();

      var un = document.getElementById('upnext');
      un.innerHTML = '';
      if (s.upnext) {
        var lab = document.createElement('span');
        lab.className = 'ulabel';
        lab.textContent = 'Up next';
        if (s.upnext.shuffle) {
          un.appendChild(lab);
          un.appendChild(document.createTextNode('Shuffle is on'));
        } else if (s.upnext.tracks && s.upnext.tracks.length) {
          un.appendChild(lab);
          for (var i = 0; i < s.upnext.tracks.length; i++) {
            if (i > 0) {
              var sep = document.createElement('span');
              sep.className = 'sep';
              sep.textContent = '\u00b7';
              un.appendChild(sep);
            }
            var t = s.upnext.tracks[i];
            un.appendChild(document.createTextNode(t.title + (t.artist ? ' \u2014 ' + t.artist : '')));
          }
        }
      }

      if (s.albumart !== lastArt) {
        lastArt = s.albumart;
        setAccent(s.albumart);
        var url = s.albumart ? 'url("' + s.albumart + '")' : 'none';
        document.getElementById('art').style.backgroundImage = url;
        document.getElementById('bg').style.backgroundImage = url;
      }
    })
    .catch(function () { lastTitle = null; setText('title', 'Connection lost - retrying...'); })
    .then(function () { clearTimeout(pollTimer); pollTimer = setTimeout(update, refresh * 1000); });
}

// ---------- Keep the TV awake ----------
// Uses the Wake Lock API where the browser allows it; otherwise plays a tiny,
// silent, looping video, which stops most TV browsers dimming or sleeping.
var KEEPAWAKE_VIDEO = 'data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAMrbW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAAB9AAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAlV0cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAB9AAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAABAAAAAQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAfQAAAAAAABAAAAAAHNbWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAABAAAAAgABVxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABeG1pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAAThzdGJsAAAAuHN0c2QAAAAAAAAAAQAAAKhhdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAABAAEABIAAAASAAAAAAAAAABFUxhdmM2MC4zMS4xMDIgbGlieDI2NAAAAAAAAAAAAAAAGP//AAAALmF2Y0MBQsAK/+EAFmdCwArZHsBEAAADAAQAAAMACDxImSABAAVoy4PLIAAAABBwYXNwAAAAAQAAAAEAAAAUYnRydAAAAAAAAApAAAAKQAAAABhzdHRzAAAAAAAAAAEAAAACAABAAAAAABRzdHNzAAAAAAAAAAEAAAABAAAAHHN0c2MAAAAAAAAAAQAAAAEAAAACAAAAAQAAABxzdHN6AAAAAAAAAAAAAAACAAAChgAAAAoAAAAUc3RjbwAAAAAAAAABAAADWwAAAGJ1ZHRhAAAAWm1ldGEAAAAAAAAAIWhkbHIAAAAAAAAAAG1kaXJhcHBsAAAAAAAAAAAAAAAALWlsc3QAAAAlqXRvbwAAAB1kYXRhAAAAAQAAAABMYXZmNjAuMTYuMTAwAAAACGZyZWUAAAKYbWRhdAAAAnAGBf//bNxF6b3m2Ui3lizYINkj7u94MjY0IC0gY29yZSAxNjQgcjMxMDggMzFlMTlmOSAtIEguMjY0L01QRUctNCBBVkMgY29kZWMgLSBDb3B5bGVmdCAyMDAzLTIwMjMgLSBodHRwOi8vd3d3LnZpZGVvbGFuLm9yZy94MjY0Lmh0bWwgLSBvcHRpb25zOiBjYWJhYz0wIHJlZj0zIGRlYmxvY2s9MTowOjAgYW5hbHlzZT0weDE6MHgxMTEgbWU9aGV4IHN1Ym1lPTcgcHN5PTEgcHN5X3JkPTEuMDA6MC4wMCBtaXhlZF9yZWY9MSBtZV9yYW5nZT0xNiBjaHJvbWFfbWU9MSB0cmVsbGlzPTEgOHg4ZGN0PTAgY3FtPTAgZGVhZHpvbmU9MjEsMTEgZmFzdF9wc2tpcD0xIGNocm9tYV9xcF9vZmZzZXQ9LTIgdGhyZWFkcz0xIGxvb2thaGVhZF90aHJlYWRzPTEgc2xpY2VkX3RocmVhZHM9MCBucj0wIGRlY2ltYXRlPTEgaW50ZXJsYWNlZD0wIGJsdXJheV9jb21wYXQ9MCBjb25zdHJhaW5lZF9pbnRyYT0wIGJmcmFtZXM9MCB3ZWlnaHRwPTAga2V5aW50PTI1MCBrZXlpbnRfbWluPTEgc2NlbmVjdXQ9NDAgaW50cmFfcmVmcmVzaD0wIHJjX2xvb2thaGVhZD00MCByYz1jcmYgbWJ0cmVlPTEgY3JmPTIzLjAgcWNvbXA9MC42MCBxcG1pbj0wIHFwbWF4PTY5IHFwc3RlcD00IGlwX3JhdGlvPTEuNDAgYXE9MToxLjAwAIAAAAAOZYiEBb///w9FAAFPf4AAAAAGQZo4CvqA';
var wakeLock = null;

function startVideoKeepAwake() {
  var v = document.getElementById('keepawake');
  if (!v) {
    v = document.createElement('video');
    v.id = 'keepawake';
    v.muted = true;
    v.loop = true;
    v.setAttribute('muted', '');
    v.setAttribute('playsinline', '');
    v.src = KEEPAWAKE_VIDEO;
    document.body.appendChild(v);
  }
  var p = v.play();
  if (p && p.catch) { p.catch(function () {}); }
}

function keepAwake() {
  if ('wakeLock' in navigator && window.isSecureContext) {
    navigator.wakeLock.request('screen')
      .then(function (lock) { wakeLock = lock; })
      .catch(startVideoKeepAwake);
  } else {
    startVideoKeepAwake();
  }
}
keepAwake();
document.addEventListener('visibilitychange', function () {
  if (document.visibilityState === 'visible') { keepAwake(); }
});
// Some browsers only allow playback after a button press on the remote
document.addEventListener('keydown', keepAwake);
document.addEventListener('click', keepAwake);
// Check every 30 seconds that the video is still playing
setInterval(function () {
  var v = document.getElementById('keepawake');
  if (v && v.paused) { startVideoKeepAwake(); }
}, 30000);

// ---------- Protect the screen from burn-in ----------
// Drift the whole layout by a few pixels every minute.
setInterval(function () {
  var dx = Math.round(Math.random() * 24 - 12);
  var dy = Math.round(Math.random() * 24 - 12);
  document.getElementById('wrap').style.transform = 'translate(' + dx + 'px,' + dy + 'px)';
}, 60000);

// ---------- Reload every 6 hours ----------
// Keeps long-running TV browsers fresh. Only reloads if the server is up.
setInterval(function () {
  fetch('/api/status', { cache: 'no-store' })
    .then(function (r) { if (r.ok) { location.reload(); } })
    .catch(function () {});
}, 6 * 60 * 60 * 1000);

update();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/status"):
            TV.seen(self.client_address[0], self.headers.get("User-Agent"))
            host = (self.headers.get("Host") or "localhost").split(":")[0]
            body = json.dumps(get_status(host)).encode("utf-8")
            self._send(200, "application/json", body)
        elif self.path.startswith("/api/art"):
            try:
                data, ctype = get_art()
            except Exception:
                data, ctype = None, None
            if data:
                self._send(200, ctype, data, cache=True)
            else:
                self._send(404, "text/plain", b"No art")
        elif self.path.startswith("/api/tv"):
            body = json.dumps(TV.debug(), indent=2).encode("utf-8")
            self._send(200, "application/json", body)
        elif self.path.startswith("/api/discogs"):
            body = json.dumps(DISCOGS.debug(), indent=2).encode("utf-8")
            self._send(200, "application/json", body)
        elif self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
        else:
            self._send(404, "text/plain", b"Not found")

    def _send(self, code, ctype, body, cache=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep the logs quiet


if __name__ == "__main__":
    print("Now-playing page on port %d" % PORT)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
