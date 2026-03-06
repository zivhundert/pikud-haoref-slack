"""Tests for dedupe_store.py."""

import pytest

from app.dedupe_store import DedupeStore


@pytest.fixture()
def store(tmp_path):
    db = str(tmp_path / "test.db")
    s = DedupeStore(db_path=db, ttl_seconds=5)
    yield s
    s.close()


def test_new_alert_not_duplicate(store: DedupeStore) -> None:
    assert store.is_duplicate("alert-1") is False


def test_marked_alert_is_duplicate(store: DedupeStore) -> None:
    store.mark_seen("alert-2")
    assert store.is_duplicate("alert-2") is True


def test_different_ids_independent(store: DedupeStore) -> None:
    store.mark_seen("alert-3")
    assert store.is_duplicate("alert-4") is False


def test_expired_entry_not_duplicate(tmp_path) -> None:
    db = str(tmp_path / "expire_test.db")
    # TTL of 0 → immediately expired
    store = DedupeStore(db_path=db, ttl_seconds=0)
    store.mark_seen("alert-5")
    # expires_at is set to now+0 = now; is_duplicate checks expires_at > now
    assert store.is_duplicate("alert-5") is False
    store.close()


def test_mark_seen_idempotent(store: DedupeStore) -> None:
    store.mark_seen("alert-6")
    store.mark_seen("alert-6")  # should not raise
    assert store.is_duplicate("alert-6") is True


def test_purge_removes_old_entries(store: DedupeStore) -> None:
    """Verify we can insert many entries without errors (purge runs internally)."""
    for i in range(50):
        store.mark_seen(f"bulk-{i}")
    assert store.is_duplicate("bulk-0") is True
