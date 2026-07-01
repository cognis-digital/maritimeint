"""Offline-safe tests for the bundled datafeeds engine (cache/catalog/snapshot).

No network: we point COGNIS_FEEDS_CACHE at a tmp dir, seed the cache by hand,
and exercise the offline read + snapshot round-trip. Fetch/update over the wire
is NOT called.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint import datafeeds as D  # noqa: E402


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIS_FEEDS_CACHE", str(tmp_path / "cache"))
    return tmp_path / "cache"


class TestCatalog:
    def test_catalog_loads(self):
        assert len(D.load_catalog().get("feeds", [])) >= 1

    def test_catalog_entries_have_id_and_url(self):
        for f in D.load_catalog()["feeds"]:
            assert "id" in f and "url" in f

    def test_list_feeds_all(self):
        assert len(D.list_feeds()) == len(D.load_catalog()["feeds"])

    def test_list_feeds_by_domain(self):
        feeds = D.load_catalog()["feeds"]
        if feeds and feeds[0].get("domain"):
            dom = feeds[0]["domain"]
            assert all(f["domain"] == dom for f in D.list_feeds(domain=dom))

    def test_ofac_sdn_in_catalog(self):
        assert any(f["id"] == "ofac-sdn" for f in D.load_catalog()["feeds"])


class TestCacheDir:
    def test_cache_dir_created(self, cache):
        d = D.cache_dir()
        assert d.exists()

    def test_cached_age_none_when_absent(self, cache):
        assert D.cached_age_hours("ofac-sdn") is None


class TestOfflineGet:
    def _seed(self, cache, feed_id="ofac-sdn", body="hello"):
        import json
        import time
        cache.mkdir(parents=True, exist_ok=True)
        (cache / f"{feed_id}.data").write_text(body, encoding="utf-8")
        (cache / f"{feed_id}.meta.json").write_text(
            json.dumps({"fetched_at": time.time(), "url": "x"}), encoding="utf-8")

    def test_offline_reads_cache(self, cache):
        self._seed(cache, body="cached-body")
        data = D.get("ofac-sdn", offline=True)
        assert "cached-body" in (data if isinstance(data, str) else str(data))

    def test_offline_missing_raises(self, cache):
        with pytest.raises((FileNotFoundError, KeyError, ConnectionError, ValueError)):
            D.get("ofac-sdn", offline=True)

    def test_cached_age_after_seed(self, cache):
        self._seed(cache)
        age = D.cached_age_hours("ofac-sdn")
        assert age is not None and age >= 0

    def test_unknown_feed_offline(self, cache):
        with pytest.raises((KeyError, FileNotFoundError, ValueError)):
            D.get("totally-unknown-feed", offline=True)


class TestSnapshot:
    def _seed(self, cache, feed_id="ofac-sdn", body="snap"):
        import json
        import time
        cache.mkdir(parents=True, exist_ok=True)
        (cache / f"{feed_id}.data").write_text(body, encoding="utf-8")
        (cache / f"{feed_id}.meta.json").write_text(
            json.dumps({"fetched_at": time.time(), "url": "x"}), encoding="utf-8")

    def test_export_then_import_roundtrip(self, cache, tmp_path, monkeypatch):
        self._seed(cache, body="roundtrip-body")
        snap = tmp_path / "snap.tar.gz"
        n = D.snapshot_export(str(snap))
        assert n >= 1 and snap.exists()
        # wipe cache, import into a fresh dir
        new_cache = tmp_path / "cache2"
        monkeypatch.setenv("COGNIS_FEEDS_CACHE", str(new_cache))
        m = D.snapshot_import(str(snap))
        assert m >= 1
        data = D.get("ofac-sdn", offline=True)
        assert "roundtrip-body" in (data if isinstance(data, str) else str(data))

    def test_export_empty_cache(self, cache, tmp_path):
        D.cache_dir()  # ensure exists, empty
        snap = tmp_path / "empty.tar.gz"
        n = D.snapshot_export(str(snap))
        assert n == 0


class TestFeedsWrapperOffline:
    def test_feeds_get_offline_missing(self, cache):
        from maritimeint import feeds as F
        with pytest.raises((KeyError, FileNotFoundError, ConnectionError, ValueError)):
            F.get("ofac-sdn", offline=True)
