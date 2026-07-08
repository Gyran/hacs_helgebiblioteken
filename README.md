# Helgebiblioteken

![Helgebiblioteken logo](custom_components/helgebiblioteken/brand/logo.png)

A Home Assistant custom integration for HelGe-biblioteken that allows you to track your library loans, reservations, and due dates.

## Features

- Track active library loans and reservations
- Monitor loan and reservation counts
- View next loan expiry date
- Binary sensors for overdue loans, loans due soon, and reservations ready for pickup
- Custom Lovelace cards for loans and reservations
- Renew loans from Home Assistant or the loans card
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

## Lovelace Cards

The integration loads card scripts automatically.

- Loans card: **type** `custom:helgebiblioteken-loans-card`, **entity** `sensor.helgebiblioteken_loan_count`
- Reservations card: **type** `custom:helgebiblioteken-reservations-card`, **entity** `sensor.helgebiblioteken_reservation_count`

In the UI editor, use **Add card → Manual** and paste YAML, or add cards in YAML mode.

Example:

```yaml
type: custom:helgebiblioteken-reservations-card
entity: sensor.helgebiblioteken_reservation_count
```

## Services

### `helgebiblioteken.refresh`

Manually refresh account data for all configured accounts or a specific account.

**Service Data:**
- `entry_id` (optional): The config entry ID to refresh. If not provided, all entries will be refreshed.

### `helgebiblioteken.renew_loan`

Renew one loan by loan ID from the loan list attributes.

**Service Data:**
- `loan_id` (required)
- `entity_id` (optional): Helgebiblioteken sensor used to resolve the integration instance
- `entry_id` (optional)

### `helgebiblioteken.renew_due_soon`

Renew renewable loans that are overdue or due within the selected number of days.

**Service Data:**
- `days` (optional, default `3`)
- `entity_id` (optional)
- `entry_id` (optional)

## Entities

The integration creates the following entities:

- `sensor.helgebiblioteken_loan_count` - Number of active loans
- `sensor.helgebiblioteken_reservation_count` - Number of active reservations
- `sensor.helgebiblioteken_next_loan_expiry` - Date of the next loan expiry
- `sensor.helgebiblioteken_last_update` - Last update timestamp (diagnostic)
- `binary_sensor.helgebiblioteken_loans_overdue` - On when at least one loan is overdue
- `binary_sensor.helgebiblioteken_loans_due_soon` - On when at least one loan is due soon
- `binary_sensor.helgebiblioteken_reservations_ready_for_pickup` - On when at least one reservation is ready for pickup
- `button.helgebiblioteken_refresh` - Button to manually refresh account data

## Automations

Example notification when a reservation is ready for pickup:

```yaml
automation:
  - alias: Bibliotek - reservation ready for pickup
    triggers:
      - trigger: state
        entity_id: binary_sensor.helgebiblioteken_reservations_ready_for_pickup
        to: "on"
    actions:
      - action: notify.notify
        data:
          title: Bibliotek
          message: Du har en reservation redo att hämtas.
```

Example notification when loans are due soon:

```yaml
automation:
  - alias: Bibliotek - loans due soon
    triggers:
      - trigger: state
        entity_id: binary_sensor.helgebiblioteken_loans_due_soon
        to: "on"
    actions:
      - action: notify.notify
        data:
          title: Bibliotek
          message: Du har lån som snart går ut.
```

## Support

- [Issue Tracker](https://github.com/gyran/hacs_helgebiblioteken/issues)
- [Documentation](https://github.com/gyran/hacs_helgebiblioteken)

## Brand & logo

Icons and logos live in [`custom_components/helgebiblioteken/brand/`](custom_components/helgebiblioteken/brand/). Home Assistant **2026.3+** loads them automatically (see [brand images](https://developers.home-assistant.io/docs/core/integration/brand_images)).

They are generated from the **official** HelGe assets on Axiell’s CDN (square + wide logo). Details and refresh steps: [`brand/README.md`](custom_components/helgebiblioteken/brand/README.md).

To **re-download and resize** after upstream changes:

`python3 -m pip install -r scripts/requirements-brand.txt` then `python3 scripts/generate_brand_images.py`

## License

This project is licensed under the MIT License.
