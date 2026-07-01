"""Tests for maritimeint.addins (backend discovery, no network) and connect mapping."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maritimeint import addins as A  # noqa: E402
from maritimeint import connect as C  # noqa: E402


def _no_backend(url):
    return None


def _all_backends(url):
    return ["test-model-a", "test-model-b"]


def _only_edgemesh(url):
    return ["em-model"] if "8780" in url else None


class TestProbeParsing:
    def test_available_all_disabled(self):
        rows = A.available(probe_fn=_no_backend)
        assert all(r["enabled"] is False for r in rows)
        assert {r["addin"] for r in rows} == {"reasoning", "vision"}

    def test_available_all_enabled(self):
        rows = A.available(probe_fn=_all_backends)
        assert all(r["enabled"] for r in rows)
        for r in rows:
            assert r["models"] == ["test-model-a", "test-model-b"]

    def test_discover_empty(self):
        assert A.discover(probe_fn=_no_backend) == {}

    def test_discover_named_backend(self):
        found = A.discover(probe_fn=_only_edgemesh)
        assert "edgemesh" in found
        assert found["edgemesh"][0].endswith("8780")

    def test_reasoning_prefers_edgemesh(self):
        rows = A.available(probe_fn=_only_edgemesh)
        reasoning = next(r for r in rows if r["addin"] == "reasoning")
        assert reasoning["backend"] == "edgemesh" and reasoning["enabled"]


class TestVisionMessages:
    def test_shape(self):
        msgs = A.build_vision_messages("http://img", note="test")
        assert msgs[0]["role"] == "user"
        content = msgs[0]["content"]
        assert any(c["type"] == "image_url" for c in content)
        assert any(c["type"] == "text" and "test" in c["text"] for c in content)

    def test_no_note(self):
        msgs = A.build_vision_messages("data:image/png;base64,AAA")
        text = next(c["text"] for c in msgs[0]["content"] if c["type"] == "text")
        assert "Context" not in text


WATCHLIST = {
    "watchlist": [
        {"mmsi": "477000001", "name": "GREY GHOST", "tier": "HIGH", "score": 8,
         "sanctioned": True, "reasons": ["ON SANCTIONS LIST (IRAN)", "AIS gap 12h"]},
        {"mmsi": "999999999", "name": "CLEAN", "tier": "LOW", "score": 1,
         "sanctioned": False, "reasons": ["loitering ~4h"]},
    ]
}


class TestConnectMapping:
    def _findings_or_skip(self):
        try:
            return C.watchlist_to_findings(WATCHLIST)
        except ImportError:
            pytest.skip("cognis-connect not installed")

    def test_mapping_or_skip(self):
        findings = self._findings_or_skip()
        assert len(findings) == 2

    def test_forward_without_sdk_raises_importerror(self):
        # if the SDK isn't installed, forward() must raise a clear ImportError.
        try:
            import cognis_connect  # noqa: F401
            pytest.skip("cognis-connect installed; ImportError path not exercised")
        except ImportError:
            with pytest.raises(ImportError, match="cognis-connect"):
                C.forward(WATCHLIST, "stix")

    def test_unknown_target(self):
        # unknown target: either ImportError (no SDK) or ValueError (SDK present)
        with pytest.raises((ImportError, ValueError)):
            C.forward(WATCHLIST, "nosuchtarget")
