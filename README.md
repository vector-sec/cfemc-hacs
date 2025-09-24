# CFEMC Energy Integration for Home Assistant

This is an unofficial Home Assistant integration for retrieving hourly energy consumption data from Coweta-Fayette EMC. It is designed to feed historical and daily energy data directly into Home Assistant's Energy Dashboard.

This integration fetches the previous day's hourly usage data once per day and can backfill historical data upon initial setup.

## Features

* Energy Dashboard Integration: Provides hourly energy data for use in the Home Assistant Energy dashboard.

* Daily Updates: Automatically fetches the previous day's usage data every 24 hours.

* Historical Backfill: On first setup, you can specify a number of days (up to 365) to backfill historical usage data.

## Installation

This integration can be installed via HACS (recommended) or by manually copying the files.
HACS Installation (Recommended)

1. Add this repository as a custom repository in HACS:

   * Go to HACS > Integrations.
  
   * Click the three-dot menu in the top right and select Custom repositories.
  
   * Paste the URL to your repository.
  
   * Select the category Integration.
  
   * Click Add.

2. The "CFEMC Energy" integration will now be available in HACS. Click Install.

3. Restart Home Assistant.

## Manual Installation

1. Download the latest release of this integration.

2. Copy the cfemc_energy directory into your Home Assistant custom_components directory.

3. Restart Home Assistant.

## Configuration

Configuration is done through the Home Assistant user interface.

1. Navigate to Settings > Devices & Services.

2. Click the Add Integration button.

3. Search for "CFEMC Energy" and select it.

4. A configuration dialog will appear. Fill in the following fields:

   * Name: A friendly name for the integration entry (e.g., "Home Energy").
  
   * Username: Your username for the CFEMC online portal.
  
   * Password: Your password for the CFEMC online portal.
  
   * Member Number: Your CFEMC member number.
  
   * Account Number: Your CFEMC account number.
  
   * Backfill Days: The number of past days of data to fetch on initial setup. Defaults to 7.

5. Click Submit. The integration will test the credentials and, if successful, complete the setup.

## Usage

After successful configuration, the integration will begin backfilling data. This may take a few minutes.

To view the data, you must add the sensor to your Energy Dashboard:

1. Navigate to Settings > Dashboards and select Energy.

2. Under the Grid Consumption section, click Add Consumption.

3. Select the "CF-EMC Energy Usage" statistic from the list.

4. Click Save.

The Energy Dashboard will begin populating with your historical and daily usage data.

## Troubleshooting

If you encounter issues during setup or data fetching, you can enable debug logging to get more information. Add the following to your `configuration.yaml` file:

```
logger:
  default: info
  logs:
    custom_components.cfemc_energy: debug
```
Then, restart Home Assistant and check the logs at Settings > System > Logs.

This is an unofficial integration and is not affiliated with Coweta-Fayette EMC. Use at your own risk.
