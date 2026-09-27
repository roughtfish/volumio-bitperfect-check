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


class Page(unittest.TestCase):
    def test_page_has_its_parts(self):
        for part in ('id="favicon"', 'id="health"', 'id="idleinfo"', 'id="progress"', 'id="upnext"', 'id="toast"',
                     'id="artpixel"', 'id="record"', 'id="cd"', 'id="cassette"'):
            self.assertIn(part, n.PAGE)
        self.assertIsNotNone(re.search(r"<script>.*</script>", n.PAGE, re.S))


if __name__ == "__main__":
    unittest.main()
