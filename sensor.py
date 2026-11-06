"""ESB Electricity Usage Sensor."""
from datetime import timedelta, datetime, timezone
import logging

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed, CoordinatorEntity,
)
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMetaData, StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)

from .const import DOMAIN
from .esb_api import ESBSmartMeter
from .readings import (
    READ_TYPE_EXPORT,
    READ_TYPE_IMPORT,
    cumulative_statistics,
    hourly_usage,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=24)
EARLIEST_STATISTIC = datetime(2000, 1, 1, tzinfo=timezone.utc)
STATISTICS = (
    (READ_TYPE_IMPORT, "consumption", "ESB Energy"),
    (READ_TYPE_EXPORT, "export", "ESB Export"),
)

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

    async_add_entities([
        ESBElectricitySensor(coordinator, config_entry)
    ])


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
        """Import historical import and export readings as separate statistics."""
        for read_type, suffix, label in STATISTICS:
            await self._async_import_statistic(data["readings"], read_type, suffix, label)

    async def _async_sum_before(self, statistic_id, hour):
        """Return the cumulative sum of the newest statistic before an hour."""
        existing = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            EARLIEST_STATISTIC,
            hour,
            {statistic_id},
            "hour",
            None,
            {"sum"},
        )
        rows = existing.get(statistic_id)
        return rows[-1]["sum"] if rows else 0

    async def _async_import_statistic(self, readings, read_type, suffix, label):
        """Rebuild the statistic for one read type from every reading in the file.

        Rewriting all hours each time completes the hour that was partial in the
        last download and replaces anything imported earlier for those hours.
        """
        statistic_id = f"{DOMAIN}:esb_{self.mprn}_{suffix}"
        hourly = hourly_usage(readings, read_type)
        if not hourly:
            read_types = sorted({reading.get("type", "") for reading in readings})
            _LOGGER.warning(f"No usable '{read_type}' readings for {statistic_id}: {read_types}")
            return

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{label} {self.mprn}",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            unit_class=SensorDeviceClass.ENERGY,
        )
        base_sum = await self._async_sum_before(statistic_id, next(iter(hourly)))
        statistics = cumulative_statistics(hourly, base_sum)

        _LOGGER.info(
            f"Importing {len(statistics)} statistics for {statistic_id}: "
            f"{statistics[0]['start']} to {statistics[-1]['start']}"
        )
        async_add_external_statistics(self.hass, metadata, statistics)

class ESBElectricitySensor(CoordinatorEntity, SensorEntity):
    """Representation of an ESB Electricity Usage sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coordinator: ESBDataUpdateCoordinator, config_entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = f"ESB Electricity {coordinator.mprn}"
        self._attr_unique_id = f"esb_{coordinator.mprn}_usage"
        self._config_entry = config_entry
        self._attr_statistics_metadata = {
            "source": DOMAIN,
            "statistic_id": f"{DOMAIN}:esb_{coordinator.mprn}_consumption",
        }

    @property
    def native_value(self):
        """Return the total cumulative usage."""
        if self.coordinator.data:
            total = self.coordinator.data.get("total_usage", 0)
            return round(total, 2) if total > 0 else 0
        return 0

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if self.coordinator.data:
            readings = self.coordinator.data.get("readings", [])

            return {
                "total_readings": len(readings),
                "total_export": round(self.coordinator.data.get("total_export", 0), 2),
                "last_updated": self.coordinator.data.get("last_updated"),
                "sample_reading": readings[0] if readings else None,
            }
        return {}
