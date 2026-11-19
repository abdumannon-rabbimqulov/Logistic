from datetime import datetime, timezone

from services.live_location_sync import rows_to_sync


def test_rows_to_sync_skips_stopped_and_bad_entries():
    rows = rows_to_sync([
        {"driver_id": 1, "lat": 41.3, "lon": 69.2, "ts": "2026-01-01T10:00:00+00:00"},
        {"driver_id": 2, "lat": 0, "lon": 0, "ts": "2026-01-01T10:00:00+00:00", "stopped": True},
        {"driver_id": 3, "lat": "x", "lon": 1, "ts": "2026-01-01T10:00:00+00:00"},
        {"driver_id": 4, "lat": 1, "lon": 1},
    ])
    assert rows == [{"driver_id": 1, "lat": 41.3, "lon": 69.2, "ts": datetime(2026, 1, 1, 10, tzinfo=timezone.utc)}]
