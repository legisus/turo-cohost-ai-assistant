import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from agent import store

def test_state_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    st = {"threads": {"123": {"last_seen": "hi", "last_sent": "", "pending": None}}}
    store.save_state(str(p), st)
    assert store.load_state(str(p)) == st

def test_load_state_missing_returns_empty(tmp_path):
    p = tmp_path / "nope.json"
    assert store.load_state(str(p)) == {"threads": {}}

def test_save_is_atomic_no_tmp_left(tmp_path):
    p = tmp_path / "state.json"
    store.save_state(str(p), {"threads": {}})
    assert not (tmp_path / "state.json.tmp").exists()
