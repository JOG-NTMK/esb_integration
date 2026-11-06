"""Tests for parsing ESB HDF data and building hourly statistics."""
from datetime import datetime, timezone

import pytest

from readings import (
    READ_TYPE_EXPORT,
    READ_TYPE_IMPORT,
    cumulative_statistics,
    hourly_usage,
    parse_usage_csv,
)

HEADER = "MPRN,Meter Serial Number,Read Value,Read Type,Read Date and End Time\r\n"
SAMPLE_CSV = (
    HEADER
    + "1,2,0.5000,Active Import Interval (kWh),05-11-2026 02:30\r\n"
    + "1,2,0.2000,Active Export Interval (kWh),05-11-2026 02:30\r\n"
    + "1,2,0.2500,Active Import Interval (kWh),05-11-2026 02:00\r\n"
    + "1,2,0.1000,Active Export Interval (kWh),05-11-2026 02:00\r\n"
    + "1,2,1.0000,Active Import Interval (kWh),05-11-2026 01:30\r\n"
)


def reading(usage, date, read_type=READ_TYPE_IMPORT):
    return {"date": date, "usage": usage, "type": read_type}


def utc(day, hour, month=11, year=2026):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def test_parse_keeps_import_and_export_totals_separate():
    parsed = parse_usage_csv(SAMPLE_CSV)

    assert parsed["total_usage"] == pytest.approx(1.75)
    assert parsed["total_export"] == pytest.approx(0.3)
    assert len(parsed["readings"]) == 5


def test_parse_preserves_read_type_and_clean_date():
    first = parse_usage_csv(SAMPLE_CSV)["readings"][0]

    assert first == reading(0.5, "05-11-2026 02:30")


def test_parse_header_only_returns_no_readings():
    parsed = parse_usage_csv(HEADER)

    assert parsed == {"total_usage": 0, "total_export": 0, "readings": []}


def test_parse_skips_row_with_invalid_value():
    csv_text = HEADER + "1,2,bad,Active Import Interval (kWh),05-11-2026 02:00\r\n"

    assert parse_usage_csv(csv_text)["readings"] == []


def test_parse_excludes_unknown_read_type_from_both_totals():
    csv_text = HEADER + "1,2,9.0,Reactive Import Interval (kvarh),05-11-2026 02:00\r\n"

    parsed = parse_usage_csv(csv_text)

    assert (parsed["total_usage"], parsed["total_export"]) == (0, 0)


def test_parse_rejects_file_without_expected_columns():
    with pytest.raises(ValueError, match="Read Date and End Time"):
        parse_usage_csv("MPRN,Read Value,Read Type,Date\r\n1,0.5,x,05-11-2026 02:00\r\n")


def test_parse_rejects_empty_file():
    with pytest.raises(ValueError, match="columns"):
        parse_usage_csv("")


def test_hourly_usage_groups_readings_by_interval_start():
    readings = [
        reading(4.0, "05-11-2026 03:00"),
        reading(3.0, "05-11-2026 02:30"),
        reading(2.0, "05-11-2026 02:00"),
        reading(1.0, "05-11-2026 01:30"),
    ]

    assert hourly_usage(readings, READ_TYPE_IMPORT) == {utc(5, 1): 3.0, utc(5, 2): 7.0}


def test_hourly_usage_only_includes_requested_type():
    readings = parse_usage_csv(SAMPLE_CSV)["readings"]

    assert hourly_usage(readings, READ_TYPE_EXPORT) == {utc(5, 2): 0.2}


def test_hourly_usage_keeps_incomplete_newest_hour():
    readings = [
        reading(3.0, "05-11-2026 02:30"),
        reading(2.0, "05-11-2026 02:00"),
        reading(1.0, "05-11-2026 01:30"),
    ]

    assert hourly_usage(readings, READ_TYPE_IMPORT)[utc(5, 2)] == 3.0


def test_hourly_usage_drops_incomplete_oldest_hour():
    readings = [
        reading(3.0, "05-11-2026 03:00"),
        reading(2.0, "05-11-2026 02:30"),
        reading(1.0, "05-11-2026 02:00"),
    ]

    assert hourly_usage(readings, READ_TYPE_IMPORT) == {utc(5, 2): 5.0}


def test_hourly_usage_keeps_both_hours_repeated_when_clocks_go_back():
    readings = [
        reading(32.0, "26-10-2025 02:00"),
        reading(16.0, "26-10-2025 01:30"),
        reading(8.0, "26-10-2025 01:00"),
        reading(4.0, "26-10-2025 01:30"),
        reading(2.0, "26-10-2025 01:00"),
        reading(1.0, "26-10-2025 00:30"),
    ]

    assert hourly_usage(readings, READ_TYPE_IMPORT) == {
        utc(25, 23, month=10, year=2025): 3.0,
        utc(26, 0, month=10, year=2025): 12.0,
        utc(26, 1, month=10, year=2025): 48.0,
    }


def test_hourly_usage_is_continuous_when_clocks_go_forward():
    readings = [
        reading(8.0, "29-03-2026 03:00"),
        reading(4.0, "29-03-2026 02:30"),
        reading(2.0, "29-03-2026 02:00"),
        reading(1.0, "29-03-2026 00:30"),
    ]

    assert hourly_usage(readings, READ_TYPE_IMPORT) == {
        utc(29, 0, month=3): 3.0,
        utc(29, 1, month=3): 12.0,
    }


def test_hourly_usage_fills_meter_gaps_with_zero():
    readings = [
        reading(2.0, "05-11-2026 05:00"),
        reading(2.0, "05-11-2026 04:30"),
        reading(1.0, "05-11-2026 02:00"),
        reading(1.0, "05-11-2026 01:30"),
    ]

    assert hourly_usage(readings, READ_TYPE_IMPORT) == {
        utc(5, 1): 2.0,
        utc(5, 2): 0,
        utc(5, 3): 0,
        utc(5, 4): 4.0,
    }


def test_hourly_usage_ignores_missing_and_malformed_dates():
    readings = [
        reading(1.0, ""),
        reading(1.0, "2026-11-05 02:00"),
        reading(1.0, "05-11-2026 02:30"),
        reading(1.0, "05-11-2026 02:00"),
    ]

    assert hourly_usage(readings, READ_TYPE_IMPORT) == {utc(5, 2): 1.0}


def test_hourly_usage_with_no_matching_readings_is_empty():
    assert hourly_usage([reading(1.0, "05-11-2026 02:00")], READ_TYPE_EXPORT) == {}


def test_cumulative_statistics_continues_from_base_sum():
    stats = cumulative_statistics({utc(5, 1): 1.0, utc(5, 2): 2.0}, 10)

    assert stats == [
        {"start": utc(5, 1), "sum": 11.0, "state": 1.0},
        {"start": utc(5, 2), "sum": 13.0, "state": 2.0},
    ]
