"""ESB Electricity Usage Sensor."""
import os
from datetime import timedelta, datetime, timezone
import logging

from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMetaData, StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
import pytz

from .const import DOMAIN
from .esb_api import ESBSmartMeter

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=24)
TZ_STRING = os.getenv('TZ', 'Europe/Dublin')
TIMEZONE = pytz.timezone(TZ_STRING)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up ESB sensor based on a config entry."""
    mprn = config_entry.data["mprn"]
    email = config_entry.data["email"]
    password = config_entry.data["password"]

    coordinator = ESBDataUpdateCoordinator(
        hass,
        mprn=mprn,
        email=email,
        password=password,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.error(f"Error setting up ESB sensor: {err}")


class ESBDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching ESB data."""

    def __init__(self, hass: HomeAssistant, mprn: str, email: str, password: str):
        """Initialize."""
        self.mprn = mprn
        self.email = email
        self.password = password
        self.api = ESBSmartMeter(mprn, email, password)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self):
        """Update data via library."""
        try:
            _LOGGER.info(f"Starting data fetch for MPRN {self.mprn}")
            data = await self.hass.async_add_executor_job(self.api.get_usage_data)
            _LOGGER.info(f"Data fetch complete: {len(data.get('readings', []))} readings")

            # After getting data, import it as statistics
            if data and data.get("readings"):
                _LOGGER.info("Calling _async_import_statistics...")
                try:
                    await self._async_import_statistics(data)
                    _LOGGER.info("Statistics import completed")
                except Exception as stats_error:
                    _LOGGER.error(f"Error importing statistics: {stats_error}", exc_info=True)
            else:
                _LOGGER.warning("No readings data to import")

            return data
        except Exception as error:
            _LOGGER.error(f"Error in _async_update_data: {error}", exc_info=True)
            raise UpdateFailed(f"Error communicating with ESB API: {error}")

    async def _async_import_statistics(self, data):
        """Import historical readings as statistics."""
        try:
            statistic_id = f"{DOMAIN}:esb_{self.mprn}_consumption"

            _LOGGER.info(f"Starting statistics import for {statistic_id}")
            _LOGGER.info(f"Total readings to process: {len(data.get('readings', []))}")

            metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"ESB Energy {self.mprn}",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                unit_class=None
            )

            # Get the last imported statistic to avoid duplicates
            last_stats = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, statistic_id, True,
                {"state", "sum", "min", "max", "mean", "last_reset"}
            )

            last_time = None
            last_sum = 0
            if statistic_id in last_stats:
                last_stat = last_stats[statistic_id][0]
                # Convert timestamp to ENV timezone for proper comparison
                last_time_utc = datetime.fromtimestamp(last_stat["start"], tz=timezone.utc)
                last_time = last_time_utc.astimezone(TIMEZONE)
                last_sum = last_stat.get("sum", 0)

                # If sum is 0, ignore last_time (means no real data was imported)
                if last_sum == 0:
                    _LOGGER.info("Last statistic has sum=0, treating as no previous data")
                    last_time = None
                else:
                    _LOGGER.info(f"Last imported statistic: {last_time}, sum: {last_sum}")
            else:
                _LOGGER.info("No previous statistics found, importing all data")

            # Process readings into statistics
            # Group half-hourly readings into hourly readings
            hourly_readings = {}
            parse_errors = 0

            for reading in data.get("readings", []):
                try:
                    reading_date_str = reading.get("date", "")
                    if not reading_date_str:
                        parse_errors += 1
                        continue

                    # Parse ESB date format: DD-MM-YYYY HH:MM
                    try:
                        naive_dt = datetime.strptime(reading_date_str, "%d-%m-%Y %H:%M")
                        # Round down to the top of the hour
                        hour_dt = naive_dt.replace(minute=0, second=0, microsecond=0)
                        reading_time = TIMEZONE.localize(hour_dt)
                    except ValueError as e:
                        if parse_errors < 5:
                            _LOGGER.warning(f"Could not parse date '{reading_date_str}': {e}")
                        parse_errors += 1
                        continue

                    usage = float(reading.get("usage", 0))

                    # Aggregate readings by hour
                    if reading_time in hourly_readings:
                        hourly_readings[reading_time] += usage
                    else:
                        hourly_readings[reading_time] = usage

                except (ValueError, KeyError) as e:
                    parse_errors += 1
                    continue

            # Convert aggregated hourly readings to statistics
            statistics = []
            cumulative_sum = last_sum
            skipped = 0

            for reading_time in sorted(hourly_readings.keys()):
                # Skip if we already have this data
                if last_time and reading_time <= last_time:
                    skipped += 1
                    continue

                usage = hourly_readings[reading_time]
                cumulative_sum += usage

                # Create statistic dict
                statistics.append({
                    "start": reading_time,
                    "sum": cumulative_sum,
                    "state": usage,
                })

            _LOGGER.info(f"Statistics summary: {len(statistics)} new, {skipped} skipped, {parse_errors} errors")

            if statistics:
                _LOGGER.info(f"Importing {len(statistics)} statistics for ESB meter {self.mprn}")
                _LOGGER.info(f"Date range: {statistics[0]['start']} to {statistics[-1]['start']}")
                async_add_external_statistics(self.hass, metadata, statistics)
                _LOGGER.info("async_add_external_statistics call completed")
            else:
                _LOGGER.warning("No statistics to import!")

        except Exception as e:
            _LOGGER.error(f"Exception in _async_import_statistics: {e}", exc_info=True)
            raise
