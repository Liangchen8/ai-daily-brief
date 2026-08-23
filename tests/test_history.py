from ai_daily.storage.history import HistoryStore


def test_history_update_and_atomic_save(tmp_path):
    path = tmp_path / "seen_items.json"
    history = HistoryStore(path)
    history.mark_sent(item_id="1", canonical_url="https://example.com/a", cluster_id=None, title="Old", content="old")
    history.save()
    loaded = HistoryStore(path)
    assert loaded.is_new_or_updated(item_id="1", canonical_url="https://example.com/a", cluster_id=None, title="Old", content="old") == (False, False)
    assert loaded.is_new_or_updated(item_id="1", canonical_url="https://example.com/a", cluster_id=None, title="New", content="new") == (True, True)

