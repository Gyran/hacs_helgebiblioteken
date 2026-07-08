class HelgebibliotekenReservationsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = null;
  }

  setConfig(config) {
    this._config = {
      ...config,
    };
    if (this._hass && this._config.entity !== undefined) {
      this.updateCard();
    }
  }

  set hass(hass) {
    this._hass = hass;
    this.updateCard();
  }

  static getStubConfig() {
    return { entity: 'sensor.helgebiblioteken_reservation_count' };
  }

  static async getConfigSchema() {
    return [
      {
        name: 'entity',
        required: true,
        selector: {
          entity: {
            filter: [
              { domain: 'sensor', integration: 'helgebiblioteken' },
            ],
          },
        },
      },
    ];
  }

  static getConfigElement() {
    return document.createElement('helgebiblioteken-reservations-card-editor');
  }

  getCardSize() {
    return 3;
  }

  _isReadyForPickup(reservation) {
    const pickupNumber = String(reservation?.pickup_number || '').trim();
    if (pickupNumber) {
      return true;
    }
    if (reservation?.pickup_expiry_date) {
      return true;
    }

    const status = String(reservation?.status || '').trim().toLowerCase();
    if (!status || ['aktiv', 'active', 'väntar', 'waiting'].includes(status)) {
      return false;
    }

    const readyTokens = [
      'klar att hämta',
      'redo att hämta',
      'kan hämtas',
      'hämtklar',
      'at pick-up',
      'ready for pickup',
      'available for pickup',
    ];
    return readyTokens.some((token) => status.includes(token));
  }

  _renderReservationLine(label, value) {
    if (!value) {
      return '';
    }
    return `<div class="reservation-line"><span class="label">${this.escapeHtml(label)}:</span> ${this.escapeHtml(String(value))}</div>`;
  }

  updateCard() {
    if (!this._hass) {
      return;
    }

    const entityId = this._config && this._config.entity;
    if (!entityId) {
      this.shadowRoot.innerHTML = `
        <ha-card>
          <div class="card-content">
            <div class="placeholder">Select an entity in the card configuration.</div>
          </div>
        </ha-card>
        <style>
          ha-card { padding: 16px; }
          .placeholder { color: var(--secondary-text-color, #757575); font-style: italic; }
        </style>
      `;
      return;
    }

    const stateObj = this._hass.states[entityId];
    if (!stateObj) {
      this.shadowRoot.innerHTML = `
        <ha-card>
          <div class="card-content">
            <div class="error">Entity ${this.escapeHtml(entityId)} not found</div>
          </div>
        </ha-card>
        <style>
          ha-card { padding: 16px; }
          .error { color: var(--error-color, #f44336); padding: 16px; }
        </style>
      `;
      return;
    }

    const reservations = stateObj.attributes.reservations || [];
    let reservationsHtml = '';

    if (reservations.length === 0) {
      reservationsHtml = '<div class="no-reservations">No active reservations</div>';
    } else {
      reservationsHtml = '<ul class="reservations-list">';
      reservations.forEach((reservation) => {
        const title = reservation.title || 'Unknown Title';
        const author = reservation.author || '';
        const readyForPickup = this._isReadyForPickup(reservation);
        const readyClass = readyForPickup ? 'ready-for-pickup' : '';
        const readyBadge = readyForPickup
          ? '<span class="badge">Ready for pickup</span>'
          : '';
        const queueText = reservation.queue_text || '';
        const validTo = reservation.valid_to || '';
        const pickupBranch = reservation.pickup_branch || '';
        const status = reservation.status || '';
        const pickupNumber = reservation.pickup_number || '';

        reservationsHtml += `
          <li class="reservation-item ${readyClass}">
            <div class="reservation-main">
              <div class="title-row">
                <span class="reservation-title">${this.escapeHtml(title)}</span>
                ${readyBadge}
              </div>
              ${author ? `<div class="reservation-author">${this.escapeHtml(author)}</div>` : ''}
              ${this._renderReservationLine('Hämtställe', pickupBranch)}
              ${this._renderReservationLine('Köplats', queueText)}
              ${this._renderReservationLine('Giltig till', validTo)}
              ${this._renderReservationLine('Status', status)}
              ${this._renderReservationLine('Löpnummer', pickupNumber)}
            </div>
          </li>
        `;
      });
      reservationsHtml += '</ul>';
    }

    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="card-content">
          ${reservationsHtml}
        </div>
      </ha-card>
      <style>
        ha-card {
          padding: 16px;
        }
        .card-content {
          padding-top: 0;
        }
        .reservations-list {
          list-style: none;
          padding: 0;
          margin: 0;
        }
        .reservation-item {
          padding: 10px 0;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          color: var(--primary-text-color, #212121);
          font-size: 14px;
        }
        .reservation-item:last-child {
          border-bottom: none;
        }
        .reservation-main {
          min-width: 0;
        }
        .title-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }
        .reservation-title {
          font-weight: 600;
        }
        .reservation-author {
          margin-top: 2px;
          color: var(--secondary-text-color, #757575);
          font-size: 13px;
        }
        .reservation-line {
          margin-top: 4px;
          font-size: 13px;
        }
        .reservation-line .label {
          color: var(--secondary-text-color, #757575);
        }
        .ready-for-pickup {
          background: color-mix(in srgb, var(--success-color, #4caf50) 10%, transparent);
          border-radius: 6px;
          padding: 10px;
          margin: 6px 0;
        }
        .badge {
          font-size: 11px;
          padding: 2px 8px;
          border-radius: 999px;
          background: var(--success-color, #4caf50);
          color: white;
          white-space: nowrap;
        }
        .no-reservations {
          text-align: center;
          padding: 20px;
          color: var(--secondary-text-color, #757575);
          font-style: italic;
        }
        .error {
          color: var(--error-color, #f44336);
          padding: 16px;
        }
      </style>
    `;
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

class HelgebibliotekenReservationsCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = {};
  }

  setConfig(config) {
    this._config = config || {};
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    this.render();
  }

  _onValueChanged(event) {
    const nextEntity = event?.detail?.value?.entity;
    if (nextEntity === this._config.entity) {
      return;
    }

    this._config = {
      type: CARD_TAG,
      ...this._config,
      entity: nextEntity,
    };

    this.dispatchEvent(
      new CustomEvent('config-changed', {
        detail: { config: this._config },
        bubbles: true,
        composed: true,
      }),
    );
  }

  render() {
    this.shadowRoot.innerHTML = `
      <div class="editor">
        <div id="form-root"></div>
      </div>
      <style>
        .editor {
          display: grid;
          gap: 12px;
        }
      </style>
    `;

    const formRoot = this.shadowRoot.getElementById('form-root');
    if (!formRoot || !this._hass) {
      return;
    }

    const form = document.createElement('ha-form');
    form.hass = this._hass;
    form.data = {
      entity: this._config.entity || '',
    };
    form.schema = [
      {
        name: 'entity',
        required: true,
        selector: {
          entity: {
            filter: [
              { domain: 'sensor', integration: 'helgebiblioteken' },
            ],
          },
        },
      },
    ];
    form.addEventListener('value-changed', (event) => this._onValueChanged(event));
    formRoot.appendChild(form);
  }
}

const CARD_TAG = 'helgebiblioteken-reservations-card';

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, HelgebibliotekenReservationsCard);
}
if (!customElements.get('helgebiblioteken-reservations-card-editor')) {
  customElements.define(
    'helgebiblioteken-reservations-card-editor',
    HelgebibliotekenReservationsCardEditor,
  );
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TAG)) {
  window.customCards.push({
    type: CARD_TAG,
    name: 'Helgebiblioteken Reservations Card',
    description: 'Show active Helgebiblioteken reservations',
    preview: true,
  });
}
