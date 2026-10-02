"""Tests for nowplaying.py.

Run from the repository root with:
    python -m unittest discover -s tests -v

They use only the standard library and never touch the network, Volumio,
Discogs, Last.fm or a TV: everything outside the program is simulated.
"""

import json
import os
import re
import sys
import tempfile
import time
import unittest
import urllib.parse
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "nowplaying"))

import nowplaying as n  # noqa: E402


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TextHelpers(unittest.TestCase):
    def test_version_format(self):
        self.assertRegex(n.VERSION, r"^\d+\.\d+\.\d+$")

    def test_norm_strips_remaster_tags(self):
        self.assertEqual(n.norm("Move on Up (2019 Remaster)"), n.norm("Move On Up"))
        self.assertEqual(n.norm("Superfly - 2019 Remaster"), "superfly")
        self.assertEqual(n.norm("The Felice Brothers"), "felice brothers")

    def test_clean_title_keeps_case(self):
        self.assertEqual(n.clean_title("Move on Up (2019 Remaster)"), "Move on Up")
        self.assertEqual(n.clean_title("Keep On Keeping On (Deluxe Edition)"), "Keep On Keeping On")

    def test_clean_artist(self):
        self.assertEqual(n.clean_artist("Lorde (2)*"), "Lorde")

    def test_dates_and_money(self):
        self.assertEqual(n.format_added("2019-02-08T10:00:00-08:00"), "8 Feb 2019")
        self.assertEqual(n.format_added(""), "")
        self.assertEqual(n.money({"value": 43.18, "currency": "GBP"}), "\u00a343.18")
        self.assertEqual(n.money(None), "")

    def test_time_ago(self):
        now = time.time()
        self.assertEqual(n.time_ago(now - 120), "2 minutes ago")
        self.assertEqual(n.time_ago(now - 3 * 86400), "3 days ago")
        self.assertEqual(n.time_ago(now - 21 * 86400), "3 weeks ago")
        self.assertEqual(n.time_ago(now - 4 * 365 * 86400), "4 years ago")

    def test_khz_formatting(self):
        self.assertEqual(n.fmt_khz(44.1), "44.1")
        self.assertEqual(n.fmt_khz(192.0), "192")


class LedAndFirmware(unittest.TestCase):
    def test_led_colours(self):
        self.assertEqual(n.led_colour(False, 44100, None)["name"], "Green")
        self.assertEqual(n.led_colour(False, 96000, None)["name"], "Green")
        self.assertEqual(n.led_colour(False, 192000, None)["name"], "Yellow")
        self.assertEqual(n.led_colour(True, 0, 128)["name"], "Cyan")
        self.assertEqual(n.led_colour(True, 0, 256)["name"], "Blue")

    def _firmware_for(self, bcd, product="iFi (by AMR) HD USB Audio", vendor="20b1"):
        root = tempfile.mkdtemp()
        dev = os.path.join(root, "1-2")
        os.makedirs(dev)
        for name, value in (("idVendor", vendor), ("product", product), ("bcdDevice", bcd)):
            with open(os.path.join(dev, name), "w") as f:
                f.write(value + "\n")
        n.FIRMWARE["t"] = 0
        with mock.patch.object(n.glob, "glob", return_value=[dev]):
            return n.dac_firmware()

    def test_firmware_variants(self):
        self.assertEqual(self._firmware_for("076c")["variant"], "c")
        self.assertTrue(self._firmware_for("076c")["upsamples"])
        self.assertEqual(self._firmware_for("076c")["version"], "7.6c")
        self.assertEqual(self._firmware_for("076b")["variant"], "b")
        self.assertEqual(self._firmware_for("0760")["variant"], "standard")

    def test_no_ifi_dac(self):
        self.assertIsNone(self._firmware_for("0100", product="Some Other DAC"))
        self.assertIsNone(self._firmware_for("0100", vendor="1234"))


class BitPerfect(unittest.TestCase):
    def setUp(self):
        self.state = {"status": "play", "artist": "Songs: Ohia", "title": "Farewell Transmission",
                      "album": "Magnolia", "samplerate": "44.1 KHz", "bitdepth": "16 bit"}
        self.dac = {"rate_khz": 48.0, "depth": 24, "label": "48 kHz / 24-bit", "dsd": None,
                    "led": n.led_colour(False, 48000, None)}
        self.clock = [1000.0]
        n.BITPERFECT.update({"key": None, "src": None, "since": 0})
        self.patches = [
            mock.patch.object(n.time, "time", lambda: self.clock[0]),
            mock.patch.object(n.urllib.request, "urlopen",
                              lambda url, timeout=3: FakeResponse(json.dumps(self.state).encode())),
            mock.patch.object(n, "volumio_json", lambda url, timeout=3: {"queue": []}),
            mock.patch.object(n, "read_dac", lambda: self.dac),
            mock.patch.object(n.DISCOGS, "lookup", lambda *a: None),
            mock.patch.object(n.LASTFM, "lookup", lambda *a: None),
            mock.patch.object(n, "dac_firmware", lambda: None),
            mock.patch.object(n, "STATE_MAX_AGE", 0),      # always read the latest simulated state
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def verdict(self):
        return n.get_status("host")["bitperfect"]

    def test_grace_period_hides_a_brief_wrong_reading(self):
        for t in range(0, 3):
            self.clock[0] = 1000 + t
            self.assertIsNone(self.verdict())
        self.state.update(samplerate="48 KHz", bitdepth="24 bit")   # real details arrive
        for t in range(3, 10):
            self.clock[0] = 1000 + t
            self.assertIsNone(self.verdict())
        self.clock[0] = 1000 + 12
        self.assertTrue(self.verdict())

    def settle(self):
        for t in range(0, 8):
            self.clock[0] = 1000 + t
            self.assertIsNone(self.verdict())
        self.clock[0] = 1000 + 9
        return self.verdict()

    def test_real_resampling_still_shows(self):
        # A hi-res source reaching the DAC at CD quality is a real problem
        self.state.update(samplerate="96 KHz", bitdepth="24 bit")
        self.dac.update(rate_khz=44.1, depth=16, label="44.1 kHz / 16-bit")
        self.assertIs(self.settle(), False)

    def test_other_rate_changes_still_show(self):
        self.state.update(samplerate="48 KHz", bitdepth="24 bit")
        self.dac.update(rate_khz=96.0, depth=24, label="96 kHz / 24-bit")
        self.assertIs(self.settle(), False)

    def test_cd_quality_report_with_more_at_the_dac_is_unconfirmed(self):
        # Volumio says 44.1/16, the DAC gets 96/24: Volumio's figure is the wrong one
        self.dac.update(rate_khz=96.0, depth=24, label="96 kHz / 24-bit")
        self.assertEqual(self.settle(), "unconfirmed")
        # the same with the rate unchanged but more bits
        self.dac.update(rate_khz=44.1, depth=24, label="44.1 kHz / 24-bit")
        self.assertEqual(self.verdict(), "unconfirmed")


class SourceLabel(unittest.TestCase):
    def test_source_shows_quality_only(self):
        self.assertEqual(n.source_info({"trackType": "flac"}, 192.0, 24)["label"], "192 kHz / 24-bit")
        self.assertEqual(n.source_info({"trackType": "tidal"}, 44.1, 16)["label"], "44.1 kHz / 16-bit")


class Scrobbling(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.patch = mock.patch.object(n, "lastfm_signed",
                                       lambda method, params, **kw: self.calls.append((method, params)) or {})
        self.patch.start()
        self.s = n.Scrobbler.__new__(n.Scrobbler)
        self.s.lock = n.threading.Lock()
        self.s.enabled = True
        self.s.creds = {"api_key": "K", "secret": "S"}
        self.s.error = ""
        self.s.error_at = 0
        self.s.last_scrobble = ""
        self.s.last_service = ""
        self.s.skipping = False
        self.s.pending = []
        self.s.track = None

    def tearDown(self):
        self.patch.stop()

    def play(self, title, seconds, duration=246, service="tidal", status="play", start=1000):
        for i in range(0, seconds + 1, 5):
            self.s._tick({"artist": "The Felice Brothers", "title": title, "album": "The Felice Brothers",
                          "duration": duration, "seek": i * 1000, "status": status, "service": service},
                         start + i, 5)
        self.s._flush()
        return [c[0] for c in self.calls]

    def test_scrobbles_after_half_the_track(self):
        self.assertEqual(self.play("Frankie's Gun!", 125), ["track.updateNowPlaying", "track.scrobble"])
        self.assertEqual(self.calls[-1][1]["track[0]"], "Frankie's Gun!")

    def test_not_before_half(self):
        self.assertEqual(self.play("Frankie's Gun!", 100), ["track.updateNowPlaying"])

    def test_tidal_connect_is_skipped(self):
        self.assertEqual(self.play("Run Chicken Run", 200, service="tidalconnect"), [])

    def test_long_track_four_minute_rule(self):
        self.assertIn("track.scrobble", self.play("Long One", 245, duration=900))

    def test_short_tracks_never_scrobble(self):
        self.assertNotIn("track.scrobble", self.play("Intro", 25, duration=25))

    def test_signature_matches_lastfm_spec(self):
        self.patch.stop()
        captured = {}

        def fake_urlopen(req, timeout=10):
            captured["url"] = req.full_url
            captured["data"] = req.data
            return FakeResponse(b"{}")

        with mock.patch.object(n.urllib.request, "urlopen", fake_urlopen):
            n.lastfm_signed("auth.getSession", {"token": "TOK"}, http_post=False, api_key="KEY", secret="SECRET")
        self.patch.start()
        query = urllib.parse.parse_qs(urllib.parse.urlparse(captured["url"]).query)
        import hashlib
        expected = hashlib.md5("api_keyKEYmethodauth.getSessiontokenTOKSECRET".encode()).hexdigest()
        self.assertEqual(query["api_sig"][0], expected)


class IdleScreen(unittest.TestCase):
    def setUp(self):
        self.clock = [10000.0]
        self.patches = [mock.patch.object(n.time, "time", lambda: self.clock[0])]
        for p in self.patches:
            p.start()
        releases = [{"id": i, "title": "Album %d" % i, "year": 2000 + i, "format": "Vinyl, LP",
                     "artists": ["Artist %d" % i], "added": "", "cover": ""} for i in range(1, 6)]
        releases.append({"id": 99, "title": "A CD", "year": 2001, "format": "CD, Album",
                         "artists": ["X"], "added": "", "cover": ""})
        self.old_releases = n.DISCOGS.releases
        n.DISCOGS.releases = releases
        n.IDLE.update({"last_play": self.clock[0], "rid": None, "since": 0, "recent": [], "plays": {}})

    def tearDown(self):
        n.DISCOGS.releases = self.old_releases
        for p in self.patches:
            p.stop()

    def test_waits_two_minutes(self):
        self.clock[0] += 60
        self.assertFalse(n.idle_info({"status": "pause"})["active"])
        self.clock[0] += 70
        self.assertTrue(n.idle_info({"status": "pause"})["active"])

    def test_rotates_without_repeats_and_skips_cds(self):
        self.clock[0] += 130
        seen = {n.idle_info({"status": "stop"})["title"]}
        for _ in range(4):
            self.clock[0] += n.IDLE_ROTATE + 1
            seen.add(n.idle_info({"status": "stop"})["title"])
        self.assertEqual(len(seen), 5)
        self.assertNotIn("A CD", seen)

    def test_playback_ends_it(self):
        self.clock[0] += 130
        self.assertTrue(n.idle_info({"status": "stop"})["active"])
        self.assertFalse(n.idle_info({"status": "play"})["active"])


class Settings(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.config = os.path.join(self.dir, "config.json")
        self.session = os.path.join(self.dir, "lastfm_session.json")
        with open(self.config, "w") as f:
            json.dump({"discogs_user": "someone", "discogs_token": "SECRET-TOKEN",
                       "lastfm_user": "someone", "lastfm_api_key": "SECRET-KEY"}, f)
        self.patches = [
            mock.patch.object(n, "CONFIG_FILE", self.config),
            mock.patch.object(n, "LASTFM_SESSION_FILE", self.session),
            mock.patch.object(n, "restart_soon", lambda: None),
        ]
        for p in self.patches:
            p.start()
        if not hasattr(n, "SCROBBLER"):
            n.SCROBBLER = n.Scrobbler()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def save(self, query):
        n.save_settings(urllib.parse.parse_qs(query, keep_blank_values=True))
        with open(self.config) as f:
            return json.load(f)

    def test_page_never_shows_secrets(self):
        page = n.settings_page()
        self.assertNotIn("SECRET-TOKEN", page)
        self.assertNotIn("SECRET-KEY", page)
        self.assertIn(n.VERSION, page)

    def test_blank_keeps_and_remove_clears(self):
        cfg = self.save("discogs_user=someone&discogs_token=&lastfm_user=someone&lastfm_api_key="
                        "&lastfm_api_key_clear=on&currency=USD&refresh_seconds=8")
        self.assertEqual(cfg["discogs_token"], "SECRET-TOKEN")
        self.assertEqual(cfg["lastfm_api_key"], "")
        self.assertEqual(cfg["currency"], "USD")
        self.assertEqual(cfg["refresh_seconds"], 8)

    def test_bad_values_are_corrected(self):
        cfg = self.save("currency=XXX&refresh_seconds=500")
        self.assertEqual(cfg["currency"], "GBP")
        self.assertEqual(cfg["refresh_seconds"], 60)

    def test_cover_style_settings(self):
        cfg = self.save("currency=GBP&refresh_seconds=5&cover_style=pixel&pixel_blocks=16&vinyl_when_owned=on")
        self.assertEqual((cfg["cover_style"], cfg["pixel_blocks"], cfg["vinyl_when_owned"]), ("pixel", 16, True))
        cfg = self.save("currency=GBP&refresh_seconds=5&cover_style=hologram&pixel_blocks=500")
        self.assertEqual((cfg["cover_style"], cfg["pixel_blocks"], cfg["vinyl_when_owned"]), ("normal", 96, False))
        cfg = self.save("currency=GBP&refresh_seconds=5&cover_style=vinyl&pixel_blocks=big")
        self.assertEqual((cfg["cover_style"], cfg["pixel_blocks"]), ("vinyl", 32))
        page = n.settings_page()
        self.assertIn('name="cover_style"', page)
        self.assertIn("Spinning vinyl", page)

    def test_removed_full_screen_style_falls_back_to_normal(self):
        self.assertNotIn("fullscreen", n.COVER_STYLES)
        self.assertEqual(self.save("currency=GBP&refresh_seconds=5&cover_style=fullscreen")["cover_style"], "normal")

    def test_every_cover_style_can_be_saved(self):
        for style in n.COVER_STYLES:
            self.assertEqual(self.save("currency=GBP&refresh_seconds=5&cover_style=" + style)["cover_style"], style)
        self.assertTrue(self.save("currency=GBP&refresh_seconds=5&pixel_gap=on")["pixel_gap"])
        self.assertFalse(self.save("currency=GBP&refresh_seconds=5")["pixel_gap"])

    def test_screen_off_setting(self):
        self.assertEqual(self.save("currency=GBP&refresh_seconds=5&tv_screen_off_minutes=30")["tv_screen_off_minutes"], 30)
        self.assertEqual(self.save("currency=GBP&refresh_seconds=5&tv_screen_off_minutes=999")["tv_screen_off_minutes"], 240)
        self.assertEqual(self.save("currency=GBP&refresh_seconds=5&tv_screen_off_minutes=later")["tv_screen_off_minutes"], 15)
        self.assertIn('name="tv_screen_off_minutes"', n.settings_page())

    def test_update_check_setting(self):
        self.assertTrue(self.save("currency=GBP&refresh_seconds=5&update_check=on")["update_check"])
        self.assertFalse(self.save("currency=GBP&refresh_seconds=5")["update_check"])
        self.assertIn('name="update_check"', n.settings_page())

    def test_scrobble_message_settings(self):
        cfg = self.save("currency=GBP&refresh_seconds=5&toast_seconds=12&toast_until_next=on")
        self.assertEqual(cfg["toast_seconds"], 12)
        self.assertTrue(cfg["toast_until_next"])
        cfg = self.save("currency=GBP&refresh_seconds=5&toast_seconds=200")
        self.assertEqual(cfg["toast_seconds"], 60)
        self.assertFalse(cfg["toast_until_next"])
        cfg = self.save("currency=GBP&refresh_seconds=5&toast_seconds=soon")
        self.assertEqual(cfg["toast_seconds"], 8)
        cfg = self.save("currency=GBP&refresh_seconds=5&toast_seconds=0")
        self.assertEqual(cfg["toast_seconds"], 0)
        self.assertIn('name="toast_seconds"', n.settings_page())

    def test_disconnect_removes_session_file(self):
        with open(self.session, "w") as f:
            json.dump({"session_key": "SK", "user": "someone", "api_key": "K", "secret": "S"}, f)
        self.save("lastfm_disconnect=on&currency=GBP&refresh_seconds=5")
        self.assertFalse(os.path.exists(self.session))


class Backup(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        files = {"config": os.path.join(self.dir, "config.json"),
                 "session": os.path.join(self.dir, "lastfm_session.json"),
                 "tv": os.path.join(self.dir, "lgtv_key.json")}
        self.files = files
        with open(files["config"], "w") as f:
            json.dump({"discogs_user": "someone", "discogs_token": "TOKEN", "lastfm_api_key": "KEY",
                       "lastfm_secret": "SECRET", "cover_style": "vinyl"}, f)
        with open(files["session"], "w") as f:
            json.dump({"session_key": "SK", "user": "someone", "api_key": "KEY", "secret": "SECRET"}, f)
        with open(files["tv"], "w") as f:
            json.dump({"client_key": "TVKEY"}, f)
        self.patches = [mock.patch.object(n, "CONFIG_FILE", files["config"]),
                        mock.patch.object(n, "LASTFM_SESSION_FILE", files["session"]),
                        mock.patch.object(n, "TV_KEY_FILE", files["tv"]),
                        mock.patch.object(n, "restart_soon", lambda: None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_backup_without_keys_has_no_secrets(self):
        text = json.dumps(n.make_backup(False))
        for secret in ("TOKEN", "KEY", "SECRET", "SK", "TVKEY"):
            self.assertNotIn('"%s"' % secret, text)
        self.assertIn("vinyl", text)

    def test_full_restore_after_a_wipe(self):
        backup = json.dumps(n.make_backup(True))
        for path in self.files.values():
            os.remove(path)
        with open(self.files["config"], "w") as f:
            f.write("{}")
        message = n.restore_backup(backup)
        self.assertIn("Last.fm connection", message)
        self.assertIn("TV pairing", message)
        with open(self.files["config"]) as f:
            self.assertEqual(json.load(f)["discogs_token"], "TOKEN")
        self.assertTrue(os.path.exists(self.files["session"]))
        self.assertTrue(os.path.exists(self.files["tv"]))

    def test_restore_without_keys_keeps_saved_keys(self):
        backup = json.dumps(n.make_backup(False))
        n.restore_backup(backup)
        with open(self.files["config"]) as f:
            self.assertEqual(json.load(f)["lastfm_secret"], "SECRET")

    def test_bad_files_are_rejected(self):
        for bad in ('{"hello": 1}', "not json", "x" * (n.MAX_BACKUP_BYTES + 1)):
            with self.assertRaises(ValueError):
                n.restore_backup(bad)


class Health(unittest.TestCase):
    def test_problems_are_reported_and_expire(self):
        if not hasattr(n, "SCROBBLER"):
            n.SCROBBLER = n.Scrobbler()
        now = time.time()
        with mock.patch.object(n.DISCOGS, "user", "someone"), \
                mock.patch.object(n.DISCOGS, "releases", [{"id": 1}]), \
                mock.patch.object(n.DISCOGS, "coll_failed_at", now):
            self.assertIn("Discogs: can't load your collection", n.health()["problems"])
        with mock.patch.object(n.DISCOGS, "user", "someone"), \
                mock.patch.object(n.DISCOGS, "releases", [{"id": 1}]), \
                mock.patch.object(n.DISCOGS, "coll_failed_at", now - 3600):
            self.assertNotIn("Discogs: can't load your collection", n.health()["problems"])


class ScrobbleConfirmations(unittest.TestCase):
    def setUp(self):
        if not hasattr(n, "SCROBBLER"):
            n.SCROBBLER = n.Scrobbler()
        self.patch = mock.patch.object(n.SCROBBLER, "enabled", True)
        self.patch.start()
        w = n.ScrobbleWatch.__new__(n.ScrobbleWatch)
        w.lock = n.threading.Lock()
        w.current, w.pending, w.seen = None, [], set()
        w.event_id, w.last_event, w.misses, w.miss_service, w.error, w.enabled = 0, None, 0, "", "", True
        self.w = w

    def tearDown(self):
        self.patch.stop()

    def play(self, title, seconds, start, service="tidalconnect", duration=300):
        for i in range(0, seconds + 1, 5):
            self.w._follow({"artist": "Songs: Ohia", "title": title, "album": "A", "duration": duration,
                            "seek": i * 1000, "status": "play", "service": service}, start + i, 5)
        return start + seconds

    def test_tidal_connect_scrobble_is_confirmed(self):
        end = self.play("Farewell Transmission", 200, 1000)
        self.w._finish(end)
        self.w._check([{"uts": 1000, "title": "Farewell Transmission", "artist": "Songs: Ohia"}], end + 60)
        self.assertEqual(self.w.last_event["by"], "Tidal")

    def test_volumio_playback_says_volumio(self):
        self.play("Frankie's Gun!", 160, 5000, service="tidal")
        self.w._check([{"uts": 5000, "title": "Frankie's Gun!", "artist": "Songs: Ohia"}], 5165)
        self.assertEqual(self.w.last_event["by"], "Volumio")

    def test_three_misses_warn_and_a_confirmation_clears(self):
        t = 20000
        for k in range(3):
            t = self.play("Song %d" % k, 200, t) + 1
        self.w._finish(t)
        self.w._expire(t + n.ScrobbleWatch.WAIT + 1)
        self.assertIn("Tidal Connect", self.w.problem())
        end = self.play("Good One", 200, t + 500)
        self.w._check([{"uts": t + 500, "title": "Good One", "artist": "Songs: Ohia"}], end)
        self.assertEqual(self.w.problem(), "")

    def test_skipped_tracks_are_not_missed(self):
        end = self.play("Skipped", 30, 9000)
        self.w._finish(end)
        self.w._expire(end + n.ScrobbleWatch.WAIT + 1)
        self.assertEqual(self.w.misses, 0)

    def test_same_track_is_not_announced_twice(self):
        end = self.play("Running on Empty", 200, 1000)
        self.w._check([{"uts": 1000, "title": "Running on Empty", "artist": "Songs: Ohia"}], end)
        self.w.current = None
        end2 = self.play("Running on Empty", 200, 1003)
        self.w._check([{"uts": 1003, "title": "Running on Empty", "artist": "Songs: Ohia"}], end2)
        self.assertEqual(self.w.last_event["id"], 1)

    def test_old_scrobbles_are_ignored(self):
        self.play("Again", 200, 40000)
        self.w._check([{"uts": 30000, "title": "Again", "artist": "Songs: Ohia"}], 40205)
        self.assertIsNone(self.w.last_event)


class SharedVolumioState(unittest.TestCase):
    def test_many_readers_share_one_request(self):
        calls = []
        clock = [5000.0]
        v = n.VolumioState()
        body = json.dumps({"status": "play", "title": "A"}).encode()
        with mock.patch.object(n.urllib.request, "urlopen",
                               lambda url, timeout=3: calls.append(url) or FakeResponse(body)), \
                mock.patch.object(n.time, "time", lambda: clock[0]):
            for _ in range(4):               # TV page, laptop page, scrobbler, watcher
                self.assertEqual(v.get()["title"], "A")
            self.assertEqual(len(calls), 1)
            clock[0] += n.STATE_MAX_AGE + 1  # the copy is now too old, so ask again
            v.get()
            self.assertEqual(len(calls), 2)

    def test_clock_going_backwards_does_not_keep_old_state(self):
        calls = []
        clock = [5000.0]
        v = n.VolumioState()
        body = json.dumps({"status": "play", "title": "A"}).encode()
        with mock.patch.object(n.urllib.request, "urlopen",
                               lambda url, timeout=3: calls.append(url) or FakeResponse(body)), \
                mock.patch.object(n.time, "time", lambda: clock[0]):
            v.get()
            clock[0] -= 3600                 # e.g. a time sync after start-up
            v.get()
            self.assertEqual(len(calls), 2)

    def test_volumio_down_is_reported(self):
        def down(url, timeout=3):
            raise OSError("connection refused")
        v = n.VolumioState()
        with mock.patch.object(n.urllib.request, "urlopen", down):
            with self.assertRaises(OSError):
                v.get()


class LiveUpdates(unittest.TestCase):
    def test_packets_from_both_protocol_versions(self):
        self.assertEqual(n.parse_eio('0{"sid":"a","pingInterval":25000}')[0], "open")
        self.assertEqual(n.parse_eio('0{"sid":"a","pingInterval":25000}')[2]["pingInterval"], 25000)
        self.assertEqual(n.parse_eio("2")[0], "ping")
        self.assertEqual(n.parse_eio("3")[0], "pong")
        self.assertEqual(n.parse_eio("40")[0], "connect")               # socket.io v2
        self.assertEqual(n.parse_eio('40{"sid":"b"}')[0], "connect")     # socket.io v4
        self.assertEqual(n.parse_eio("41")[0], "disconnect")
        kind, name, data = n.parse_eio('42["pushState",{"title":"A"}]')
        self.assertEqual((kind, name, data), ("event", "pushState", {"title": "A"}))
        self.assertEqual(n.parse_eio('4213["pushState",{"title":"B"}]')[2], {"title": "B"})   # with an ack id
        self.assertEqual(n.parse_eio("42not json")[0], "other")

    def test_pushed_state_is_shared_and_announced(self):
        v = n.VolumioState()
        before = n.CHANGES["n"]
        v.pushed({"status": "play", "title": "Pushed"})
        self.assertEqual(n.CHANGES["n"], before + 1)
        with mock.patch.object(n.LIVE, "connected", True), \
                mock.patch.object(n.urllib.request, "urlopen", side_effect=AssertionError("should not ask")):
            self.assertEqual(v.get()["title"], "Pushed")      # no request while live and recent

    def test_position_allows_for_the_age_of_the_report(self):
        v = n.VolumioState()
        clock = [1000.0]
        with mock.patch.object(n.time, "time", lambda: clock[0]):
            v.pushed({"status": "play", "title": "A", "seek": 30000, "duration": 100})
            state = v.state
            clock[0] += 7
            self.assertEqual(v.position(state), 37000)            # 7 seconds later
            state["status"] = "pause"
            self.assertEqual(v.position(state), 30000)            # paused: no time added
            state["status"], clock[0] = "play", clock[0] + 90
            self.assertEqual(v.position(state), 100000)           # never beyond the track's end
            clock[0] += 300
            self.assertEqual(v.position(state), 30000)            # too old to guess from: left as reported

    def test_new_track_is_checked_again_once_settled(self):
        v = n.VolumioState()
        timers = []
        class FakeTimer:
            def __init__(self, delay, fn):
                timers.append(delay)
                self.daemon = True
            def start(self):
                pass
        with mock.patch.object(n.threading, "Timer", FakeTimer):
            v.pushed({"status": "play", "title": "A", "seek": 1000})
            v.pushed({"status": "play", "title": "A", "seek": 5000})     # same track: no re-check
            self.assertEqual(timers, [])
            v.pushed({"status": "play", "title": "B", "seek": 5000})     # new track, old position
            self.assertEqual(timers, list(n.RECHECK_AFTER))

    def test_regular_checks_announce_only_real_changes(self):
        v = n.VolumioState()
        body = [json.dumps({"status": "play", "title": "A", "seek": 1000}).encode()]
        with mock.patch.object(n.urllib.request, "urlopen", lambda url, timeout=3: FakeResponse(body[0])):
            v._fetch()
            start = n.CHANGES["n"]
            body[0] = json.dumps({"status": "play", "title": "A", "seek": 4000}).encode()   # only the position moved
            v._fetch()
            self.assertEqual(n.CHANGES["n"], start)
            body[0] = json.dumps({"status": "play", "title": "B", "seek": 0}).encode()      # a new track
            v._fetch()
            self.assertEqual(n.CHANGES["n"], start + 1)


class StuckVolumio(unittest.TestCase):
    def run_steps(self, steps):
        w, t, out = n.StaleWatch(), 1000.0, []
        for secs, status, running, title in steps:
            end = t + secs
            while t < end:
                w.check({"status": status, "artist": "X", "title": title}, running, t)
                t += 5
            out.append(w.problem(t))
        return out

    def test_no_false_alarms(self):
        self.assertEqual(self.run_steps([(120, "play", True, "A"), (60, "pause", False, "A"),
                                         (10, "play", False, "B"), (120, "play", True, "B")]), ["", "", "", ""])

    def test_pressing_previous_once_is_fine(self):
        steps = [(5, "play", True, t) for t in ("A", "B", "A")] + [(60, "play", True, "A")]
        self.assertTrue(all(p == "" for p in self.run_steps(steps)))

    def test_mismatches_warn_after_30_seconds_and_clear(self):
        out = self.run_steps([(20, "play", False, "A"), (20, "play", False, "A"), (20, "play", True, "A")])
        self.assertEqual(out[0], "")
        self.assertIn("nothing is reaching the DAC", out[1])
        self.assertEqual(out[2], "")
        out = self.run_steps([(40, "stop", True, "A")])
        self.assertIn("look stuck", out[0])

    def test_flipping_tracks(self):
        out = self.run_steps([(5, "play", True, t) for t in ("A", "B", "A", "B", "A")] + [(150, "play", True, "A")])
        self.assertIn("flipping", out[4])
        self.assertEqual(out[5], "")

    def test_restart_needs_the_live_connection(self):
        live = n.VolumioLive()
        with self.assertRaises(IOError):
            live.command("reboot")
        sent = []
        live.connected = True
        live.ws = type("FakeWS", (), {"send": lambda self, text: sent.append(text)})()
        live.command("reboot")
        self.assertEqual(sent, ['42["reboot"]'])


class UpdateNotice(unittest.TestCase):
    CHANGELOG = """# Changelog

## 2.1.0 (1 October 2026)

### Added

- **Similar artists** from Last.fm, shown on the idle screen. More details here.
- A second change

## 2.0.0 (30 September 2026)

- Older change
"""

    def test_reads_the_newest_version_and_notes(self):
        version, notes = n.parse_changelog(self.CHANGELOG)
        self.assertEqual(version, "2.1.0")
        self.assertEqual(notes, ["Similar artists from Last.fm, shown on the idle screen.", "A second change"])

    def test_version_comparison_is_numeric(self):
        self.assertGreater(n.version_tuple("1.10.0"), n.version_tuple("1.9.0"))
        self.assertEqual(n.version_tuple("rubbish"), (0,))

    def test_notice_only_for_newer_versions(self):
        u = n.UpdateCheck()
        body = self.CHANGELOG.encode()
        with mock.patch.object(n.urllib.request, "urlopen", lambda req, timeout=10: FakeResponse(body)):
            u.check()
        with mock.patch.object(n, "VERSION", "2.0.0"):
            self.assertTrue(u.available())
        with mock.patch.object(n, "VERSION", "2.1.0"):
            self.assertFalse(u.available())

    def test_offline_shows_no_notice(self):
        u = n.UpdateCheck()
        def down(req, timeout=10):
            raise OSError("no network")
        with mock.patch.object(n.urllib.request, "urlopen", down):
            u.check()
        self.assertTrue(u.error)
        self.assertFalse(u.available())


class UpNext(unittest.TestCase):
    def test_queue_only_fetched_when_the_track_changes(self):
        calls = []
        queue = {"queue": [{"name": "A", "artist": "X"}, {"name": "B", "artist": "X"}, {"name": "C", "artist": "X"}]}
        clock = [1000.0]
        n.UPNEXT.update({"key": None, "t": 0, "result": None})
        with mock.patch.object(n, "volumio_json", lambda url, timeout=3: calls.append(url) or queue), \
                mock.patch.object(n.time, "time", lambda: clock[0]):
            state = {"artist": "X", "title": "A", "album": "", "position": 0}
            for i in range(20):                      # 20 page updates, 5 seconds apart
                clock[0] += 5
                self.assertEqual(n.up_next(state)["tracks"][0]["title"], "B")
            self.assertEqual(len(calls), 1)
            state = {"artist": "X", "title": "B", "album": "", "position": 1}   # next track
            self.assertEqual(n.up_next(state)["tracks"][0]["title"], "C")
            self.assertEqual(len(calls), 2)
            clock[0] += n.UPNEXT_REFRESH + 1         # queue re-checked now and then
            n.up_next(state)
            self.assertEqual(len(calls), 3)

    def test_shuffle_needs_no_queue(self):
        with mock.patch.object(n, "volumio_json", side_effect=AssertionError("should not fetch")):
            self.assertTrue(n.up_next({"random": True})["shuffle"])


class TvScreen(unittest.TestCase):
    def setUp(self):
        self.tv = n.LGTV.__new__(n.LGTV)
        self.tv.lock = n.threading.Lock()
        self.tv.ip, self.tv.key, self.tv.status, self.tv.error, self.tv.last_ok = "10.0.0.9", "K", "", "", ""
        self.tv.last_play, self.tv.screen_off, self.tv.screen_off_at = 0, False, 0
        self.tv.screen_status, self.tv.screen_error, self.tv.screen_uri = "On", "", 0
        self.calls = []
        self.tv.screen = lambda on: self.calls.append("on" if on else "off")
        self.tv.nudge = lambda: self.calls.append("nudge")
        self.patches = [mock.patch.object(n, "TV_ENABLED", True), mock.patch.object(n, "TV_SCREEN_OFF_MIN", 15),
                        mock.patch.object(n, "TV_ONLY_PLAYING", True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def tick(self, minutes, playing, page_open=True):
        now = 100000 + minutes * 60
        self.tv.last_seen = now if page_open else 0
        self.tv._tick(now, playing, 0)

    def test_screen_off_after_idle_and_back_on_with_music(self):
        self.tick(0, True)
        self.tick(10, False)
        self.assertNotIn("off", self.calls)
        self.tick(16, False)
        self.assertIn("off", self.calls)
        self.calls.clear()
        self.tick(17, False)
        self.assertEqual(self.calls, [])            # no nudges while the screen is off
        self.tick(18, True)
        self.assertEqual(self.calls[0], "on")

    def test_not_off_when_the_tv_is_showing_something_else(self):
        self.tick(0, True)
        self.tick(30, False, page_open=False)
        self.assertNotIn("off", self.calls)

    def test_zero_minutes_means_never(self):
        with mock.patch.object(n, "TV_SCREEN_OFF_MIN", 0):
            self.tick(0, True)
            self.tick(120, False)
        self.assertNotIn("off", self.calls)


class TvScreenCommands(unittest.TestCase):
    """The TV refuses direct screen commands, so the notification route is used."""

    class FakeSocket:
        def __init__(self):
            self.sent, self.replies = [], []

        def send(self, text):
            m = json.loads(text)
            self.sent.append(m["uri"])
            if m["uri"].endswith("createAlert"):
                reply = {"type": "response", "id": m["id"], "payload": {"returnValue": True, "alertId": "a1"}}
            elif m["uri"].endswith("closeAlert"):
                reply = {"type": "response", "id": m["id"], "payload": {"returnValue": True}}
            else:
                reply = {"type": "error", "id": m["id"], "error": "404 no such service or method"}
            self.replies.append(json.dumps(reply))

        def recv(self):
            return self.replies.pop(0)

        def close(self):
            pass

    def test_falls_back_to_the_notification_route_and_remembers_it(self):
        tv = n.LGTV.__new__(n.LGTV)
        tv.screen_uri, tv.screen_method = 0, ""
        sock = self.FakeSocket()
        tv._connect = lambda: (sock, "ws://tv")
        self.assertTrue(tv.screen(False))
        self.assertEqual(tv.screen_method, "notification workaround")
        self.assertEqual(sock.sent[-2:], ["ssap://system.notifications/createAlert",
                                          "ssap://system.notifications/closeAlert"])
        sock.sent.clear()
        tv.screen(True)                               # next time it goes straight there
        self.assertEqual(sock.sent[0], "ssap://system.notifications/createAlert")

    def test_all_routes_refused_gives_a_clear_error(self):
        tv = n.LGTV.__new__(n.LGTV)
        tv.screen_uri, tv.screen_method = 0, ""
        sock = self.FakeSocket()
        sock_send = sock.send

        def refuse_everything(text):
            m = json.loads(text)
            sock.sent.append(m["uri"])
            sock.replies.append(json.dumps({"type": "error", "id": m["id"], "error": "401 insufficient permissions"}))
        sock.send = refuse_everything
        tv._connect = lambda: (sock, "ws://tv")
        with self.assertRaises(IOError) as ctx:
            tv.screen(False)
        self.assertIn("401 insufficient permissions", str(ctx.exception))


class Page(unittest.TestCase):
    def test_progress_bar_judges_movement_on_volumios_own_figure(self):
        self.assertIn("seek_raw", n.PAGE)
        self.assertIn("var reportMoved = raw !== pos.lastReported;", n.PAGE)

    def test_page_has_its_parts(self):
        for part in ('id="favicon"', 'id="health"', 'id="idleinfo"', 'id="progress"', 'id="upnext"', 'id="toast"',
                     'id="artpixel"', 'id="record"', 'id="cd"', 'id="cassette"', 'startLive();'):
            self.assertIn(part, n.PAGE)
        self.assertIsNotNone(re.search(r"<script>.*</script>", n.PAGE, re.S))


if __name__ == "__main__":
    unittest.main()
