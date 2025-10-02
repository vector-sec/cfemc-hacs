"""Data update coordinator for the CF-EMC Energy integration."""
from __future__ import annotations

from datetime import timedelta, date, datetime
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
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
            update_interval=timedelta(hours=12),
        )
        self.api = api
        self.check_days = backfill_days
        self.last_successful_run_timestamp = None

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        _LOGGER.debug("Starting data validation and update process.")
        
        today = dt_util.now().date()
        yesterday = today - timedelta(days=1)
        
        start_date_of_check = today - timedelta(days=self.check_days)
        start_datetime_of_check = dt_util.as_utc(datetime.combine(start_date_of_check, datetime.min.time()))
        end_datetime_of_check = dt_util.as_utc(datetime.combine(today, datetime.min.time()))

        statistic_id = f"{DOMAIN}:energy_usage_{self.api.account_number}"

        stats = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start_datetime_of_check,
            end_datetime_of_check,
            [statistic_id],
            "day",
            None,
            {"sum"},
        )

        # **FIX:** Create a dictionary to easily compare a day's sum to the previous day's.
        daily_sums = {}
        if statistic_id in stats:
            for daily_stat in stats[statistic_id]:
                stat_date = dt_util.as_local(dt_util.utc_from_timestamp(daily_stat['start'])).date()
                daily_sums[stat_date] = daily_stat.get('sum')

        dates_with_data = set()
        # **FIX:** Iterate through the dates and compare the sum to the previous day.
        # This correctly identifies days with no *new* usage.
        previous_day_sum = -1.0 # Initialize with a value that can't be matched
        for current_date in sorted(daily_sums.keys()):
            current_sum = daily_sums[current_date]
            if current_sum is not None and current_sum > previous_day_sum:
                dates_with_data.add(current_date)
            previous_day_sum = current_sum
        
        _LOGGER.debug(f"Identified the following dates with actual usage data: {sorted(list(dates_with_data))}")

        missing_dates = []
        current_date_to_check = start_date_of_check
        while current_date_to_check <= yesterday:
            if current_date_to_check not in dates_with_data:
                missing_dates.append(current_date_to_check)
            current_date_to_check += timedelta(days=1)

        if not missing_dates:
            _LOGGER.info("No missing historical data found. Statistics are up to date.")
            return self.data
            
        _LOGGER.info(f"Found missing data for the following dates: {missing_dates}")
        
        all_hourly_data = []
        for missing_date in missing_dates:
            _LOGGER.info(f"Fetching data for missing date: {missing_date.strftime('%Y-%m-%d')}")
            try:
                hourly_data = await self.hass.async_add_executor_job(
                    self.api.get_hourly_data, missing_date, missing_date
                )
                if hourly_data:
                    await self._insert_statistics(hourly_data)
                    all_hourly_data.extend(hourly_data)
                else:
                    _LOGGER.warning(f"No data was returned for {missing_date}. It may not be available from the utility yet.")
            except Exception as e:
                _LOGGER.error(f"Failed to fetch or process data for {missing_date}: {e}")
        
        self.last_successful_run_timestamp = dt_util.now()
        _LOGGER.info("Finished processing missing data.")
        return all_hourly_data[-24:] if all_hourly_data else self.data


    async def _insert_statistics(self, hourly_data: list):
        """Insert historical energy data into Home Assistant's statistics."""
        if not hourly_data:
            return

        statistic_id = f"{DOMAIN}:energy_usage_{self.api.account_number}"
        
        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )

        usage_sum = 0.0
        if last_stats and statistic_id in last_stats and last_stats[statistic_id]:
            current_sum = last_stats[statistic_id][0].get('sum')
            if isinstance(current_sum, (int, float)):
                 usage_sum = current_sum

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
