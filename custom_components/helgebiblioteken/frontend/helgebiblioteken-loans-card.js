class HelgebibliotekenLoansCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = null;
  }

  setConfig(config) {
    this._config = config || {};
    if (this._hass && this._config.entity !== undefined) {
      this.updateCard();
    }
  }

  set hass(hass) {
    this._hass = hass;
    this.updateCard();
  }

  static getStubConfig() {
    return { entity: 'sensor.helgebiblioteken_loan_count' };
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
      {
        name: 'title',
        selector: { text: {} },
      },
    ];
  }

  getCardSize() {
    return 3;
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

    const loans = stateObj.attributes.loans || [];

    let loansHtml = '';
    if (loans.length === 0) {
      loansHtml = '<div class="no-loans">No active loans</div>';
    } else {
      loansHtml = '<ul class="loans-list">';
      loans.forEach((loan) => {
        const loanTitle = loan.title || 'Unknown Title';
        const dueDate = loan.due_date;
        const expiryHtml = dueDate
          ? `<span class="loan-expiry">Expires: ${this.escapeHtml(dueDate)}</span>`
          : '';
        loansHtml += `<li class="loan-item"><span class="loan-title">${this.escapeHtml(loanTitle)}</span>${expiryHtml ? `<br>${expiryHtml}` : ''}</li>`;
      });
      loansHtml += '</ul>';
    }

    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="card-content">
          ${loansHtml}
        </div>
      </ha-card>
      <style>
        ha-card {
          padding: 16px;
        }
        .card-header {
          padding-bottom: 12px;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          margin-bottom: 12px;
        }
        .name {
          font-size: 16px;
          font-weight: 500;
          color: var(--primary-text-color, #212121);
        }
        .card-content {
          padding-top: 0;
        }
        .loans-list {
          list-style: none;
          padding: 0;
          margin: 0;
        }
        .loan-item {
          padding: 8px 0;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          color: var(--primary-text-color, #212121);
          font-size: 14px;
        }
        .loan-expiry {
          font-size: 12px;
          color: var(--secondary-text-color, #757575);
        }
        .loan-item:last-child {
          border-bottom: none;
        }
        .no-loans {
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

const CARD_TAG = 'helgebiblioteken-loans-card';

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, HelgebibliotekenLoansCard);
}
