# ESB Networks Smart Meter Integration for Home Assistant

A custom Home Assistant integration that fetches electricity usage data from ESB Networks (Ireland) and imports it as long-term statistics with full historical data.

## Features

- 🔌 **Automatic data import** - Fetches your smart meter readings from ESB Networks
- 📊 **Full historical data** - Imports all available historical readings (typically 2+ years)
- ⏱️ **Hourly statistics** - Aggregates half-hourly readings into hourly statistics
- 📈 **Energy Dashboard compatible** - Works seamlessly with Home Assistant's Energy Dashboard
- 🔄 **Daily updates** - Automatically fetches new data once per day
- 💾 **Development cache mode** - Cache data during development to avoid ESB rate limits

## Prerequisites

- Home Assistant instance
- ESB Networks account with linked smart meter ([Create account here](https://myaccount.esbnetworks.ie))
- Your electricity meter MPRN (Meter Point Reference Number)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots menu (top right) and select "Custom repositories"
4. Add this repository URL and select category "Integration"
5. Click "Install"
6. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/esb_integration` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "ESB Integration"
4. Enter your credentials:
   - **MPRN**: Your electricity meter number
   - **Email**: Your ESB Networks account email
   - **Password**: Your ESB Networks account password

The integration will immediately fetch your historical data. This may take 30-60 seconds for the initial import.

## Viewing Your Data

### Energy Dashboard

1. Go to **Settings** → **Dashboards** → **Energy**
2. Click **Add Consumption**
3. Under "Statistics", select **ESB Energy [YOUR_MPRN]**
4. Save
5. If you export to the grid, click **Add Return** and select **ESB Export [YOUR_MPRN]**

### Statistics Graph Card

1. Add a new card to your dashboard
2. Select **Statistics Graph**
3. Choose the statistic: **ESB Energy [YOUR_MPRN]**
4. Configure time period (hour/day/week/month/year)

## Important Notes

### ESB Rate Limiting

⚠️ **ESB Networks limits logins to 2 per 24 hours from the same IP address.**

- The integration updates once every 24 hours by default
- Manual updates count toward this limit
- Exceeding the limit triggers human verification (captcha)
- Limits reset at midnight Irish time (UTC)
- If blocked, wait until midnight to try again

### Data Format

- ESB provides half-hourly readings (00:00, 00:30, 01:00, 01:30, etc.)
- The integration aggregates these into hourly statistics required by Home Assistant
- Example: 21:00 (1.044 kWh) + 21:30 (0.538 kWh) = Hour 21:00 total: 1.582 kWh

## Development

### Enabling Cache Mode

To avoid hitting ESB's rate limit during development:

1. Set environment variable: `ESB_DEBUG_CACHE=true`
2. First successful fetch will cache data to `/config/esb_cache.json`
3. Subsequent updates use cached data instead of hitting ESB API

**Docker Compose example:**
```yaml
environment:
  - ESB_DEBUG_CACHE=true
```

**Remember to set `ESB_DEBUG_CACHE=false` for production use!**

### Debug Logging

Add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.esb_integration: debug
```

### Manual Update

Trigger a manual data fetch:

**Developer Tools** → **Actions**
- Service: `homeassistant.update_entity`
- Target: `sensor.esb_electricity_[YOUR_MPRN]`

## Troubleshooting

### "Login failed - too many retries"

You've exceeded ESB's 2 login per 24-hour limit. Wait until midnight (Irish time) and try again.

### "No usable readings"

The download worked but no readings could be turned into statistics. The log message lists the read types that were found.

1. Check logs for parsing errors
2. Verify your MPRN is correct
3. Ensure your meter is linked to your ESB account
4. Try clearing statistics and re-importing (see below)

For **ESB Export**, this is expected if your meter doesn't report export.

### Statistics don't show up

Imported data is a statistic, not a sensor history. In the Energy Dashboard and Statistics Graph Card, select **ESB Energy [YOUR_MPRN]**, not the `sensor.esb_electricity_[YOUR_MPRN]` entity.

### Clearing Statistics

To delete and re-import statistics:

**Developer Tools** → **Actions**
```yaml
service: recorder.purge_entities
data:
  entity_id:
    - sensor.esb_electricity_[YOUR_MPRN]
  keep_days: 0
```

Then manually trigger an update.

## Credits

This integration uses the ESB Networks API scraping logic from:
- [badger707/esb-smart-meter-reading-automation](https://github.com/badger707/esb-smart-meter-reading-automation)

Special thanks to badger707 for documenting the ESB Networks API authentication flow.

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by ESB Networks. Use at your own risk.

## Support

For issues, feature requests, or contributions, please open an issue on GitHub.