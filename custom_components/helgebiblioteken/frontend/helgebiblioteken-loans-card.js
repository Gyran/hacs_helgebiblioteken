class HelgebibliotekenLoansCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = null;
    this._renewingLoanId = null;
    this._renewingDueSoon = false;
    this._errorMessage = '';
  }

  _isBusy() {
    return this._renewingLoanId !== null || this._renewingDueSoon;
  }

  setConfig(config) {
    const parsedDays = Number(config?.renew_within_days);
    this._config = {
      ...config,
      renew_within_days: Number.isInteger(parsedDays) && parsedDays >= 0 ? parsedDays : 3,
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
    return { entity: 'sensor.helgebiblioteken_loan_count', renew_within_days: 3 };
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
        name: 'renew_within_days',
        required: false,
        selector: {
          number: {
            min: 0,
            max: 30,
            step: 1,
            mode: 'box',
          },
        },
      },
    ];
  }

  static getConfigElement() {
    return document.createElement('helgebiblioteken-loans-card-editor');
  }

  getCardSize() {
    return 3;
  }

  _getEntryId(entityId) {
    return this._hass?.entities?.[entityId]?.config_entry_id || null;
  }

  _parseIsoDate(dateStr) {
    if (!dateStr || typeof dateStr !== 'string') {
      return null;
    }
    const match = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) {
      return null;
    }
    const parsed = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  _isDueSoonLoan(loan, days) {
    const due = this._parseIsoDate(loan?.due_date);
    if (!due || loan?.can_renew === false || !loan?.loan_id || loan?.renewal_count === 0) {
      return false;
    }
    const now = new Date();
    const todayUtc = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    const dueUtc = Date.UTC(due.getUTCFullYear(), due.getUTCMonth(), due.getUTCDate());
    const daysUntilDue = Math.floor((dueUtc - todayUtc) / 86400000);
    return daysUntilDue <= days;
  }

  async _callRenewLoan(entityId, loanId) {
    if (!loanId || this._isBusy() || !this._hass) {
      return;
    }
    this._renewingLoanId = String(loanId);
    this._errorMessage = '';
    this.updateCard();
    try {
      const serviceData = { loan_id: String(loanId) };
      if (entityId) {
        serviceData.entity_id = entityId;
      }
      const entryId = this._getEntryId(entityId);
      if (entryId) {
        serviceData.entry_id = entryId;
      }
      await this._hass.callService('helgebiblioteken', 'renew_loan', serviceData);
    } catch (err) {
      this._errorMessage = err?.message || 'Kunde inte låna om';
    } finally {
      this._renewingLoanId = null;
      this.updateCard();
    }
  }

  async _callRenewDueSoon(entityId, days) {
    if (this._isBusy() || !this._hass) {
      return;
    }
    this._renewingDueSoon = true;
    this._errorMessage = '';
    this.updateCard();
    try {
      const serviceData = { days };
      if (entityId) {
        serviceData.entity_id = entityId;
      }
      const entryId = this._getEntryId(entityId);
      if (entryId) {
        serviceData.entry_id = entryId;
      }
      await this._hass.callService('helgebiblioteken', 'renew_due_soon', serviceData);
    } catch (err) {
      this._errorMessage = err?.message || 'Kunde inte låna om nära';
    } finally {
      this._renewingDueSoon = false;
      this.updateCard();
    }
  }

  _attachEventHandlers(entityId, dueSoonDays) {
    const root = this.shadowRoot?.querySelector('.card-content');
    if (!root) {
      return;
    }
    root.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }
      const loanBtn = target.closest('.renew-btn');
      if (loanBtn) {
        const loanId = loanBtn.dataset.loanId;
        void this._callRenewLoan(entityId, loanId);
        return;
      }
      const dueSoonBtn = target.closest('.renew-due-soon-btn');
      if (dueSoonBtn) {
        void this._callRenewDueSoon(entityId, dueSoonDays);
      }
    });
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
    const dueSoonDays = Number.isInteger(this._config?.renew_within_days)
      ? this._config.renew_within_days
      : 3;
    const dueSoonCount = loans.filter((loan) => this._isDueSoonLoan(loan, dueSoonDays)).length;
    const dueSoonDisabled = this._isBusy() || dueSoonCount === 0;
    const dueSoonLabelBase = `Låna om nära${dueSoonCount > 0 ? ` (${dueSoonCount})` : ''}`;
    const dueSoonLabel = this._renewingDueSoon ? 'Lånar om…' : dueSoonLabelBase;

    let loansHtml = '';
    if (loans.length === 0) {
      loansHtml = '<div class="no-loans">No active loans</div>';
    } else {
      loansHtml = '<ul class="loans-list">';
      loans.forEach((loan) => {
        const loanTitle = loan.title || 'Unknown Title';
        const loanId = loan.loan_id ? String(loan.loan_id) : '';
        const dueDate = loan.due_date;
        const expiryHtml = dueDate
          ? `<span class="loan-expiry">Expires: ${this.escapeHtml(dueDate)}</span>`
          : '';
        const canRenew = loan.can_renew !== false && !!loanId && loan.renewal_count !== 0;
        const isRenewingThis = loanId && this._renewingLoanId === loanId;
        const renewalsLeft = Number.isInteger(loan.renewal_count)
          ? `<span class="loan-renewal-count">Omlån kvar: ${loan.renewal_count}</span>`
          : '';
        loansHtml += `
          <li class="loan-item">
            <div class="loan-main">
              <span class="loan-title">${this.escapeHtml(loanTitle)}</span>
              ${expiryHtml ? `<br>${expiryHtml}` : ''}
              ${renewalsLeft ? `<br>${renewalsLeft}` : ''}
            </div>
            <button
              class="renew-btn"
              data-loan-id="${this.escapeHtml(loanId)}"
              ${!canRenew || this._isBusy() ? 'disabled' : ''}
            >${isRenewingThis ? 'Lånar om…' : 'Låna om'}</button>
          </li>
        `;
      });
      loansHtml += '</ul>';
    }

    const actionTitle = `Låna om alla som går ut inom ${dueSoonDays} dagar`;
    const errorHtml = this._errorMessage
      ? `<div class="renew-error">${this.escapeHtml(this._errorMessage)}</div>`
      : '';

    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="card-content">
          ${loansHtml}
          <div class="actions-row">
            <button
              class="renew-due-soon-btn"
              title="${this.escapeHtml(actionTitle)}"
              ${dueSoonDisabled ? 'disabled' : ''}
            >${this.escapeHtml(dueSoonLabel)}</button>
          </div>
          ${errorHtml}
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
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 10px;
        }
        .loan-expiry {
          font-size: 12px;
          color: var(--secondary-text-color, #757575);
        }
        .loan-renewal-count {
          font-size: 12px;
          color: var(--secondary-text-color, #757575);
        }
        .loan-main {
          min-width: 0;
        }
        .renew-btn, .renew-due-soon-btn {
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 6px;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);
          padding: 4px 10px;
          cursor: pointer;
          white-space: nowrap;
        }
        .renew-btn[disabled], .renew-due-soon-btn[disabled] {
          opacity: 0.6;
          cursor: default;
        }
        .actions-row {
          margin-top: 12px;
          display: flex;
          justify-content: flex-end;
        }
        .renew-error {
          margin-top: 10px;
          color: var(--error-color, #f44336);
          font-size: 13px;
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
    this._attachEventHandlers(entityId, dueSoonDays);
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

class HelgebibliotekenLoansCardEditor extends HTMLElement {
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
    const nextDays = Number(event?.detail?.value?.renew_within_days);
    const normalizedDays = Number.isInteger(nextDays) && nextDays >= 0 ? nextDays : 3;
    if (nextEntity === this._config.entity && normalizedDays === this._config.renew_within_days) {
      return;
    }

    this._config = {
      type: CARD_TAG,
      ...this._config,
      entity: nextEntity,
      renew_within_days: normalizedDays,
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
      renew_within_days: Number.isInteger(this._config.renew_within_days)
        ? this._config.renew_within_days
        : 3,
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
      {
        name: 'renew_within_days',
        required: false,
        selector: {
          number: {
            min: 0,
            max: 30,
            step: 1,
            mode: 'box',
          },
        },
      },
    ];
    form.addEventListener('value-changed', (event) => this._onValueChanged(event));
    formRoot.appendChild(form);
  }
}

const CARD_TAG = 'helgebiblioteken-loans-card';

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, HelgebibliotekenLoansCard);
}
if (!customElements.get('helgebiblioteken-loans-card-editor')) {
  customElements.define('helgebiblioteken-loans-card-editor', HelgebibliotekenLoansCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TAG)) {
  window.customCards.push({
    type: CARD_TAG,
    name: 'Helgebiblioteken Loans Card',
    description: 'Show active Helgebiblioteken loans',
    preview: true,
  });
}
