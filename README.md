# Helgebiblioteken

A Home Assistant custom integration for HelGe-biblioteken that allows you to track your library loans and get notifications about upcoming due dates.

## Features

- Track active library loans
- Monitor loan count
- View next loan expiry date
- Custom Lovelace card to display all loans
- Manual refresh button
- Automatic updates every hour

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to Integrations
3. Click the three dots menu (⋮) in the top right
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/gyran/hacs_helgebiblioteken`
6. Select "Integration" as the category
7. Click "Add"
8. Search for "Helgebiblioteken" and install it
9. Restart Home Assistant

### Manual Installation

1. Download the latest release
2. Copy the `custom_components/helgebiblioteken` folder to your Home Assistant `custom_components` directory
3. Restart Home Assistant

## Configuration

1. Go to Settings → Devices & Services
2. Click "Add Integration"
3. Search for "Helgebiblioteken"
4. Enter your HelGe-biblioteken username and password
5. Complete the setup

## Lovelace Card

The integration loads the card script automatically. Add a card with **type** `custom:helgebiblioteken-loans-card` and set **entity** to a Helgebiblioteken sensor (for example the loan count sensor). In the UI editor, use **Add card → Manual** and paste YAML, or add the card in YAML mode.

## Services

### `helgebiblioteken.refresh`

Manually refresh loan data for all configured accounts or a specific account.

**Service Data:**
- `entry_id` (optional): The config entry ID to refresh. If not provided, all entries will be refreshed.

## Entities

The integration creates the following entities:

- `sensor.helgebiblioteken_loan_count` - Number of active loans
- `sensor.helgebiblioteken_next_loan_expiry` - Date of the next loan expiry
- `sensor.helgebiblioteken_last_update` - Last update timestamp (diagnostic)
- `button.helgebiblioteken_refresh` - Button to manually refresh loan data

## Support

- [Issue Tracker](https://github.com/gyran/hacs_helgebiblioteken/issues)
- [Documentation](https://github.com/gyran/hacs_helgebiblioteken)

## License

This project is licensed under the MIT License.
