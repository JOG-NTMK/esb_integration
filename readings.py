"""Parse ESB HDF interval data and convert it into hourly statistics."""
import csv
from datetime import datetime, timedelta, timezone
import logging

import pytz

_LOGGER = logging.getLogger(__name__)

READ_TYPE_IMPORT = "Active Import Interval (kWh)"
READ_TYPE_EXPORT = "Active Export Interval (kWh)"
DATE_COLUMN = "Read Date and End Time"
VALUE_COLUMN = "Read Value"
TYPE_COLUMN = "Read Type"
DATE_FORMAT = "%d-%m-%Y %H:%M"
ESB_TIMEZONE = pytz.timezone("Europe/Dublin")
INTERVAL = timedelta(minutes=30)
HOUR = timedelta(hours=1)
READINGS_PER_HOUR = 2


def parse_usage_csv(csv_text):
    """Parse an HDF file into readings with separate import and export totals.

    Args:
        csv_text: Contents of the HDF file, including its header row.

    Returns:
        A dict with `total_usage` (import kWh), `total_export` (export kWh) and
        `readings`, a list of dicts with `date`, `usage` and `type`.

    Raises:
        ValueError: If the file does not have the expected columns.
    """
    reader = csv.DictReader(csv_text.splitlines())
    columns = reader.fieldnames or []
    missing = {DATE_COLUMN, VALUE_COLUMN, TYPE_COLUMN} - set(columns)
    if missing:
        raise ValueError(f"HDF file is missing columns {sorted(missing)}, found {columns}")

    totals = {READ_TYPE_IMPORT: 0, READ_TYPE_EXPORT: 0}
    readings = []

    for row in reader:
        try:
            usage = float(row[VALUE_COLUMN])
        except (TypeError, ValueError) as e:
            _LOGGER.warning(f"Error parsing row {row}: {e}")
            continue

        read_type = row[TYPE_COLUMN]
        if read_type in totals:
            totals[read_type] += usage
        else:
            _LOGGER.warning(f"Unrecognised read type '{read_type}' excluded from totals")

        readings.append({
            "date": row[DATE_COLUMN],
            "usage": usage,
            "type": read_type,
        })

    return {
        "total_usage": totals[READ_TYPE_IMPORT],
        "total_export": totals[READ_TYPE_EXPORT],
        "readings": readings,
    }


def _interval_hour(end_time, is_repeat):
    """Return the UTC hour containing the half hour that ended at a local time.

    Args:
        end_time: Naive Irish local time from the HDF file.
        is_repeat: True if this local time was already seen in the newest-first
            file, which makes it the earlier occurrence on the night the clocks
            go back.
    """
    occurrences = sorted(
        ESB_TIMEZONE.localize(end_time, is_dst=is_dst).astimezone(timezone.utc)
        for is_dst in (True, False)
    )
    end_utc = occurrences[0] if is_repeat else occurrences[-1]
    return (end_utc - INTERVAL).replace(minute=0)


def _collect_hours(readings, read_type):
    """Return usage and reading counts per hour for one read type."""
    usage_by_hour = {}
    counts = {}
    seen = set()
    parse_errors = 0

    for reading in readings:
        if reading.get("type") != read_type:
            continue
        try:
            end_time = datetime.strptime(reading.get("date", ""), DATE_FORMAT)
            usage = float(reading.get("usage", 0))
        except (TypeError, ValueError) as e:
            if parse_errors < 5:
                _LOGGER.warning(f"Could not parse reading {reading}: {e}")
            parse_errors += 1
            continue

        hour = _interval_hour(end_time, end_time in seen)
        seen.add(end_time)
        usage_by_hour[hour] = usage_by_hour.get(hour, 0) + usage
        counts[hour] = counts.get(hour, 0) + 1

    if parse_errors:
        _LOGGER.warning(f"Skipped {parse_errors} unparseable '{read_type}' readings")
    return usage_by_hour, counts


def hourly_usage(readings, read_type):
    """Add up half-hourly readings into a continuous run of hours.

    Hours the meter did not report are filled with zero. The oldest hour is
    dropped if the file only covers part of it, so it cannot replace a complete
    hour imported earlier. The newest hour is kept even if incomplete, because
    the next import replaces it.

    Args:
        readings: Readings as returned by `parse_usage_csv`.
        read_type: The read type to include.

    Returns:
        Dict of UTC hour to kWh, in chronological order.
    """
    usage_by_hour, counts = _collect_hours(readings, read_type)
    if not usage_by_hour:
        return {}

    hour = min(usage_by_hour)
    last_hour = max(usage_by_hour)
    if counts[hour] < READINGS_PER_HOUR and hour < last_hour:
        hour += HOUR

    continuous = {}
    while hour <= last_hour:
        continuous[hour] = usage_by_hour.get(hour, 0)
        hour += HOUR
    return continuous


def cumulative_statistics(hourly, base_sum):
    """Convert hourly usage into statistics with a running sum.

    Args:
        hourly: Dict of UTC hour to kWh, in chronological order.
        base_sum: Cumulative sum of the hour before the first one in `hourly`.

    Returns:
        List of dicts with `start`, `sum` and `state`.
    """
    statistics = []
    cumulative_sum = base_sum

    for hour, usage in hourly.items():
        cumulative_sum += usage
        statistics.append({"start": hour, "sum": cumulative_sum, "state": usage})

    return statistics
