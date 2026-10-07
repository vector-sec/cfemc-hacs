"""Data update coordinator for the CF-EMC Energy integration."""
from __future__ import annotations

from datetime import timedelta, datetime
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
try:
    from homeassistant.components.recorder.models import StatisticMeanType
except ImportError:
    StatisticMeanType = None
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
            update_interval=timedelta(hours=1),
        )
        self.api = api
        self.check_days = backfill_days
        self.last_successful_run_timestamp = None

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        _LOGGER.debug("Starting CF-EMC data validation and update process.")

        today = dt_util.now().date()
        yesterday = today - timedelta(days=1)
        start_date_of_check = today - timedelta(days=self.check_days)

        start_local_dt = dt_util.start_of_local_day(start_date_of_check)
        start_utc_dt = dt_util.as_utc(start_local_dt)
        end_local_dt = dt_util.start_of_local_day(today)
        end_utc_dt = dt_util.as_utc(end_local_dt)

        statistic_id = f"{DOMAIN}:energy_usage_{self.api.account_number}"

        # Query existing hourly statistics during the check period
        stats = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start_utc_dt,
            end_utc_dt,
            [statistic_id],
            "hour",
            None,
            {"sum", "state"},
        )

        hours_per_date: dict = {}
        daily_kwh: dict = {}
        if statistic_id in stats and stats[statistic_id]:
            for hourly_stat in stats[statistic_id]:
                stat_date = dt_util.as_local(dt_util.utc_from_timestamp(hourly_stat['start'])).date()
                hours_per_date[stat_date] = hours_per_date.get(stat_date, 0) + 1
                daily_kwh[stat_date] = daily_kwh.get(stat_date, 0.0) + (hourly_stat.get('state') or 0.0)

        _LOGGER.debug(
            "Hours recorded per date between %s and %s: %s",
            start_date_of_check,
            yesterday,
            hours_per_date,
        )

        # Identify dates that are missing, incomplete (< 23 hours), or recorded as all-zero from prior failed reads
        missing_dates = []
        cur_date = start_date_of_check
        while cur_date <= yesterday:
            count = hours_per_date.get(cur_date, 0)
            usage = daily_kwh.get(cur_date, 0.0)
            if count < 23 or (count >= 23 and usage == 0.0):
                missing_dates.append(cur_date)
            cur_date += timedelta(days=1)

        if not missing_dates:
            _LOGGER.debug("All historical statistics from %s to %s are up to date.", start_date_of_check, yesterday)
            # Calculate yesterday's usage from existing statistics for the sensor state
            yesterday_stats = [
                stat.get('state', 0.0) or 0.0
                for stat in stats.get(statistic_id, [])
                if dt_util.as_local(dt_util.utc_from_timestamp(stat['start'])).date() == yesterday
            ]
            yesterday_kwh = round(sum(yesterday_stats), 2) if yesterday_stats else None
            self.last_successful_run_timestamp = dt_util.now()
            return {
                "yesterday_kwh": yesterday_kwh,
                "hourly_data": self.data.get("hourly_data", []) if isinstance(self.data, dict) else [],
            }

        _LOGGER.info(
            "Found %d missing dates to fetch: %s",
            len(missing_dates),
            [d.strftime('%Y-%m-%d') for d in missing_dates],
        )

        all_hourly_data = []
        fetched_dates = []
        errors = []

        for missing_date in missing_dates:
            date_str = missing_date.strftime('%Y-%m-%d')
            _LOGGER.info("Fetching CF-EMC hourly data for date: %s", date_str)
            try:
                hourly_data = await self.hass.async_add_executor_job(
                    self.api.get_hourly_data, missing_date, missing_date
                )
                if hourly_data:
                    all_hourly_data.extend(hourly_data)
                    fetched_dates.append(missing_date)
                else:
                    if missing_date == yesterday:
                        _LOGGER.info(
                            "Yesterday's data (%s) is not yet published by CF-EMC. Will recheck next hour.",
                            date_str,
                        )
                    else:
                        _LOGGER.warning("No data returned for %s from CF-EMC.", date_str)
            except Exception as err:
                _LOGGER.error("Failed to fetch CF-EMC data for %s: %s", date_str, err)
                errors.append((date_str, err))

        if not all_hourly_data:
            if errors and not fetched_dates:
                raise UpdateFailed(f"Errors occurred while fetching CF-EMC data: {errors}")
            return self.data

        # Insert all fetched hourly data in a single chronological batch to maintain continuous cumulative sum
        await self._insert_statistics(all_hourly_data)

        self.last_successful_run_timestamp = dt_util.now()

        # Compute yesterday's usage if available
        yesterday_kwh = None
        yesterday_fetched = [item['usage'] for item in all_hourly_data if item['time'].date() == yesterday]
        if yesterday_fetched:
            yesterday_kwh = round(sum(yesterday_fetched), 2)
        elif statistic_id in stats:
            yesterday_existing = [
                stat.get('state', 0.0) or 0.0
                for stat in stats[statistic_id]
                if dt_util.as_local(dt_util.utc_from_timestamp(stat['start'])).date() == yesterday
            ]
            if yesterday_existing:
                yesterday_kwh = round(sum(yesterday_existing), 2)

        return {
            "yesterday_kwh": yesterday_kwh,
            "hourly_data": all_hourly_data[-24:],
        }

    async def _insert_statistics(self, all_hourly_data: list):
        """Insert historical energy data into Home Assistant's statistics with running sum."""
        if not all_hourly_data:
            return

        statistic_id = f"{DOMAIN}:energy_usage_{self.api.account_number}"

        # Sort all hourly data chronologically
        all_hourly_data.sort(key=lambda x: x['time'])

        earliest_time = all_hourly_data[0]['time']
        earliest_utc = dt_util.as_utc(earliest_time)

        # Retrieve the latest statistic from Home Assistant's recorder
        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum", "start"}
        )

        running_sum = 0.0
        if last_stats and statistic_id in last_stats and last_stats[statistic_id]:
            last_stat = last_stats[statistic_id][0]
            last_start_ts = last_stat.get('start')
            last_start_dt = dt_util.utc_from_timestamp(last_start_ts) if isinstance(last_start_ts, (int, float)) else None

            # If the earliest new record is at or after the latest existing stat, continue from its sum
            if last_start_dt and earliest_utc >= last_start_dt:
                current_sum = last_stat.get('sum')
                if isinstance(current_sum, (int, float)):
                    running_sum = current_sum
            else:
                # We are inserting historical data that precedes the latest statistic in the database.
                # Query the sum of the last statistic right before earliest_utc
                prior_start = earliest_utc - timedelta(days=self.check_days + 1)
                prior_stats = await get_instance(self.hass).async_add_executor_job(
                    statistics_during_period,
                    self.hass,
                    prior_start,
                    earliest_utc,
                    [statistic_id],
                    "hour",
                    None,
                    {"sum"},
                )
                if statistic_id in prior_stats and prior_stats[statistic_id]:
                    last_prior_sum = prior_stats[statistic_id][-1].get('sum')
                    if isinstance(last_prior_sum, (int, float)):
                        running_sum = last_prior_sum

        statistics_to_add = []
        for data in all_hourly_data:
            running_sum += data['usage']
            statistics_to_add.append(
                StatisticData(
                    start=data['time'],
                    state=data['usage'],
                    sum=round(running_sum, 4),
                )
            )

        metadata_kwargs = {
            "has_mean": False,
            "has_sum": True,
            "name": "CF-EMC Energy Usage",
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        }

        if StatisticMeanType is not None:
            metadata_kwargs["mean_type"] = StatisticMeanType.NONE

        try:
            metadata = StatisticMetaData(unit_class="energy", **metadata_kwargs)
        except TypeError:
            metadata_kwargs.pop("mean_type", None)
            metadata = StatisticMetaData(**metadata_kwargs)

        async_add_external_statistics(self.hass, metadata, statistics_to_add)
        _LOGGER.info(
            "Successfully queued %d hourly energy statistics for %s (cumulative sum: %.2f to %.2f kWh).",
            len(statistics_to_add),
            statistic_id,
            statistics_to_add[0]["sum"],
            statistics_to_add[-1]["sum"],
        )
