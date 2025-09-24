"""Data update coordinator for the CF-EMC Energy integration."""
from __future__ import annotations

from datetime import timedelta, datetime
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.util import dt as dt_util

from .api import CFEMCApi
from .const import DOMAIN, CONF_BACKFILL_DAYS

_LOGGER = logging.getLogger(__name__)


class EMCDataCoordinator(DataUpdateCoordinator):
    """Handle fetching and updating CF-EMC energy data."""

    def __init__(self, hass: HomeAssistant, api: CFEMCApi, backfill_days: int) -> None:
        """Initialize the data coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=24),  # Run once a day
        )
        self.api = api
        self.backfill_days = backfill_days
        self._first_run = True

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            today = dt_util.now().date()
            
            if self._first_run:
                _LOGGER.info(f"Starting backfill process for the last {self.backfill_days} days.")
                # Loop through each day in the backfill period
                for i in range(self.backfill_days, 0, -1):
                    target_date = today - timedelta(days=i)
                    _LOGGER.info(f"Backfilling data for: {target_date.strftime('%Y-%m-%d')}")
                    
                    # Fetch data for this single day
                    hourly_data = await self.hass.async_add_executor_job(
                        self.api.get_hourly_data, target_date, target_date
                    )
                    
                    # Insert statistics for this single day
                    await self._insert_statistics(hourly_data)

                self._first_run = False
            else:
                _LOGGER.info("Fetching hourly data for the previous day.")
                yesterday = today - timedelta(days=1)
                hourly_data = await self.hass.async_add_executor_job(
                    self.api.get_hourly_data, yesterday, yesterday
                )
                await self._insert_statistics(hourly_data)

        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def _insert_statistics(self, hourly_data: list):
        """Insert historical energy data into Home Assistant's statistics."""
        _LOGGER.debug(f"Received {len(hourly_data)} hourly records to process for statistics.")

        if not hourly_data:
            _LOGGER.warning("No hourly data received from API to insert into statistics. Aborting.")
            return

        statistic_id = f"{DOMAIN}:energy_usage_{self.api.account_number}"
        _LOGGER.debug(f"Preparing to insert statistics for ID: {statistic_id}")

        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )

        usage_sum = 0.0
        if last_stats and statistic_id in last_stats and last_stats[statistic_id]:
            # Safely get the 'sum', defaulting to 0.0 if it's None or the key is missing
            usage_sum = last_stats[statistic_id][0].get('sum') or 0.0

        _LOGGER.debug(f"Starting with a historical sum of {usage_sum} kWh.")

        statistics_to_add = []
        # Sort data by time to ensure chronological processing
        hourly_data.sort(key=lambda x: x['time'])
        
        for data in hourly_data:
            from_time = data['time']
            usage = data['usage']
            
            # This logic assumes we are always adding to the most recent sum.
            # For backfilling, it's better to ensure the sum is correct for the specific day.
            # However, HA's `get_last_statistics` is the simplest approach that works well.
            usage_sum += usage

            statistics_to_add.append(
                StatisticData(
                    start=from_time,
                    state=usage,
                    sum=usage_sum,
                )
            )

        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name="CF-EMC Energy Usage",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )

        async_add_external_statistics(self.hass, metadata, statistics_to_add)
        _LOGGER.info(f"Successfully inserted {len(statistics_to_add)} new hourly energy statistics for {statistic_id}.")

