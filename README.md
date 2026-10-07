# CF-EMC Energy Integration for Home Assistant

This is an unofficial Home Assistant integration for retrieving energy consumption data from Coweta-Fayette EMC (CF-EMC). It is designed to feed historical and daily hourly energy statistics directly into Home Assistant's Energy Dashboard.

The integration automatically polls the CF-EMC portal every hour to retrieve newly published meter data as soon as it becomes available from the utility, and can backfill historical data.

---

## Features

* **Energy Dashboard Integration**: Feeds hourly energy statistics directly into the Home Assistant Energy dashboard.
* **Smart Meter 30-Minute Interval Support**: Intelligently handles 30-minute AMI meter intervals with automatic hourly aggregation, while maintaining backwards compatibility for 60-minute historical archives.
* **Automated Hourly Polling**: Checks hourly for newly published meter data. If the utility experiences a publishing delay for yesterday's readings, the integration automatically retries each hour rather than waiting a full 24 hours.
* **Historical Backfill**: Automatically checks and backfills historical usage data (defaults to 7 days, configurable up to 365 days).
* **Dynamic Reconfiguration**: Easily adjust backfill days at any time via the integration's **Configure** button without re-adding the integration.
* **Multi-Account Support**: Supports multiple meters or accounts under the same login credentials.

---

## Provided Entities & Statistics

* **Long-Term Statistic**: `cfemc_energy:energy_usage_<account_number>`
  * Provides continuous hourly consumption data for Home Assistant's Energy Dashboard.
* **Yesterday's Total Usage**: `sensor.cf_emc_energy_yesterday_s_total_usage`
  * Displays the total kilowatt-hours (kWh) consumed yesterday, with extra attributes for account number, member number, and update timestamps.
* **Last Successful Update**: `sensor.cf_emc_energy_last_successful_update`
  * Timestamp of the most recent successful data retrieval from CF-EMC.

---

## Installation

This integration can be installed via HACS (recommended) or manually.

### HACS Installation (Recommended)

1. In Home Assistant, navigate to **HACS > Integrations**.
2. Click the three-dot menu in the top right and select **Custom repositories**.
3. Enter the repository URL: `https://github.com/vector-sec/cfemc-hacs`
4. Select the category **Integration** and click **Add**.
5. Search for **CF-EMC Energy** in HACS and click **Download**.
6. Restart Home Assistant.

### Manual Installation

1. Download the latest release zip from GitHub.
2. Copy the `custom_components/cfemc_energy` directory into your Home Assistant `/config/custom_components/` directory.
3. Restart Home Assistant.

---

## Configuration

Configuration is handled entirely through the Home Assistant UI:

1. Navigate to **Settings > Devices & Services**.
2. Click **Add Integration**.
3. Search for **CF-EMC Energy** and select it.
4. Fill in the following fields:
   * **Name**: A friendly name for the integration entry (e.g., "CF-EMC Energy").
   * **Username**: Your username for the CF-EMC online portal.
   * **Password**: Your password for the CF-EMC online portal.
   * **Member Number**: Your CF-EMC member number.
   * **Account Number**: Your CF-EMC account number (e.g., `001`, `003`).
   * **Days of historical data to fetch**: Number of past days to verify and backfill (defaults to 7).
5. Click **Submit**. The integration will test your credentials and begin backfilling data upon completion.

### Reconfiguring Options
You can change the historical verification window at any time:
1. Go to **Settings > Devices & Services**.
2. Locate the **CF-EMC Energy** card and click **Configure**.
3. Adjust the number of backfill days and click **Submit**.

---

## Energy Dashboard Setup

To view your usage in the Home Assistant Energy Dashboard:

1. Navigate to **Settings > Dashboards > Energy**.
2. Under the **Electricity Grid** section, find **Grid Consumption** and click **Add Consumption**.
3. Select the **CF-EMC Energy Usage** statistic (`cfemc_energy:energy_usage_<account_number>`).
4. Click **Save**.

> ⚠️ **Important**: Only add the statistic under **Grid Consumption**. Do **not** add `Yesterday's Total Usage` to **Return to grid** (Return to grid is strictly reserved for solar panels or batteries exporting electricity back to the grid).

---

## Troubleshooting & Debug Logging

If you encounter issues during setup or data fetching, you can enable debug logging by adding the following to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.cfemc_energy: debug
```

Restart Home Assistant and view logs under **Settings > System > Logs**.

---

*Disclaimer: This is an unofficial community integration and is not affiliated with or endorsed by Coweta-Fayette EMC. Use at your own risk.*
