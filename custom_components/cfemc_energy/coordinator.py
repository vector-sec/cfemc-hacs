"""Data update coordinator for the CF-EMC Energy integration."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.util import dt as dt_util

from .api import CFEMCApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class EMCDataCoordinator(DataUpdateCoordinator):
    """Handle fetching and updating CF-EMC energy data."""

    def __init__(self, hass: HomeAssistant, api: CFEMCApi, backfill_days: int) -> None:
        """Initialize the data coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=24),
        )
        self.api = api
        self.backfill_days = backfill_days
        self.last_successful_run_timestamp = None

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            today = dt_util.now().date()
            yesterday = today - timedelta(days=1)
            all_hourly_data = []

            statistic_id = f"{DOMAIN}:energy_usage_{self.api.account_number}"
            
            last_stats_list = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, statistic_id, True, {"start"}
            )

            if not last_stats_list or statistic_id not in last_stats_list:
                _LOGGER.info(f"No existing statistics found. Starting initial backfill process for the last {self.backfill_days} days.")
                for i in range(self.backfill_days, 0, -1):
                    target_date = today - timedelta(days=i)
                    _LOGGER.info(f"Backfilling data for: {target_date.strftime('%Y-%m-%d')}")
                    hourly_data = await self.hass.async_add_executor_job(
                        self.api.get_hourly_data, target_date, target_date
                    )
                    await self._insert_statistics(hourly_data)
                
                all_hourly_data = await self.hass.async_add_executor_job(
                    self.api.get_hourly_data, yesterday, yesterday
                )
            
            else:
                last_stat_entry = last_stats_list[statistic_id][0]
                start_time = last_stat_entry['start']

                if isinstance(start_time, float):
                    start_time = dt_util.utc_from_timestamp(start_time)

                last_stat_date = dt_util.as_local(start_time).date()
                _LOGGER.debug(f"Most recent statistic is for date: {last_stat_date}. Yesterday was: {yesterday}.")

                if last_stat_date >= yesterday:
                    _LOGGER.info("Statistics are up to date. Skipping fetch.")
                    return self.data
                
                _LOGGER.info("Existing statistics are stale. Fetching hourly data for the previous day.")
                hourly_data = await self.hass.async_add_executor_job(
                    self.api.get_hourly_data, yesterday, yesterday
                )
                await self._insert_statistics(hourly_data)
                all_hourly_data = hourly_data
            
            self.last_successful_run_timestamp = dt_util.now()
            return all_hourly_data

        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def _insert_statistics(self, hourly_data: list):
        """Insert historical energy data into Home Assistant's statistics."""
        if not hourly_data:
            _LOGGER.warning("No hourly data received from API to insert into statistics.")
            return

        statistic_id = f"{DOMAIN}:energy_usage_{self.api.account_number}"
        
        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )

        usage_sum = 0.0
        if last_stats and statistic_id in last_stats and last_stats[statistic_id]:
            usage_sum = last_stats[statistic_id][0].get('sum') or 0.0

        statistics_to_add = []
        hourly_data.sort(key=lambda x: x['time'])
        
        for data in hourly_data:
            usage_sum += data['usage']
            statistics_to_add.append(
                StatisticData(start=data['time'], state=data['usage'], sum=usage_sum)
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
        _LOGGER.info(f"Successfully processed {len(statistics_to_add)} hourly energy statistics for {statistic_id}.")

