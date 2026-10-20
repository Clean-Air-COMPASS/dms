import { beforeEach, describe, expect, it } from 'vitest';
import i18n from '../i18n';
import {
  formatJobRunEventSummary,
  formatJobRunStatus,
  formatJobRunSummary,
} from '../jobRunPresentation';

const commonSummary = {
  devices_processed: 3,
  devices_created: 0,
  sensors_processed: 12,
  sensors_created: 0,
  measurements_received: 286,
  measurements_inserted: 284,
  measurements_updated: 0,
  measurements_skipped: 2,
};

describe('job run summary presentation', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('renders interrupted as a human-readable localized status', async () => {
    expect(formatJobRunStatus('interrupted')).toBe('Interrupted');
    await i18n.changeLanguage('es');
    expect(formatJobRunStatus('interrupted')).toBe('Interrumpida');
  });

  it('shows received, inserted, and skipped counts for a normal import', () => {
    expect(formatJobRunEventSummary(commonSummary)).toBe(
      '3 devices · 286 received · 284 inserted · 2 skipped'
    );
  });

  it('shows both inserted and updated counts for an update-heavy import', () => {
    expect(formatJobRunEventSummary({
      ...commonSummary,
      measurements_inserted: 20,
      measurements_updated: 264,
    })).toBe(
      '3 devices · 286 received · 20 inserted · 264 updated · 2 skipped'
    );
  });

  it('shows device and sensor creation on a reference initialization import', () => {
    expect(formatJobRunEventSummary({
      ...commonSummary,
      devices_created: 3,
      sensors_created: 12,
    })).toBe(
      '3 devices created · 12 sensors created · 286 received · 284 inserted · 2 skipped'
    );
  });

  it('distinguishes no new data from a zero-device run', () => {
    expect(formatJobRunEventSummary({
      ...commonSummary,
      measurements_received: 0,
      measurements_inserted: 0,
      measurements_skipped: 0,
    })).toBe('3 devices checked · 0 received · no new measurements');

    expect(formatJobRunEventSummary({
      ...commonSummary,
      devices_processed: 0,
      sensors_processed: 0,
      measurements_received: 0,
      measurements_inserted: 0,
      measurements_skipped: 0,
    })).toBe('0 devices configured · no measurements requested');
  });

  it('shows real QC outcomes and omits QC when none are present', () => {
    expect(formatJobRunEventSummary({
      ...commonSummary,
      qc: {
        evaluated: 286,
        passed: 282,
        flagged: 4,
        indeterminate: 0,
      },
    })).toBe(
      '3 devices · 286 received · 284 inserted · 2 skipped · QC: 282 passed, 4 flagged'
    );
    expect(formatJobRunEventSummary(commonSummary)).not.toContain('QC:');
  });

  it('keeps the Data Source latest-import summary concise', () => {
    expect(formatJobRunSummary(commonSummary)).toBe('284 inserted · 2 skipped');
  });

  it('shows a fixed reference failure only when current summary data contains it', () => {
    expect(formatJobRunEventSummary({
      ...commonSummary,
      reference_locations_failed: [
        { region: 'sao_paulo', location_id: '175911' },
      ],
    })).toContain(
      'AirGradient reference location 175911 (São Paulo) could not be loaded'
    );

    expect(formatJobRunEventSummary({
      ...commonSummary,
      reference_regions_missing: ['rio_de_janeiro'],
    })).toBe(
      '3 devices · 286 received · 284 inserted · 2 skipped'
    );
  });

  it('uses the Spanish resources for operational terminology', async () => {
    await i18n.changeLanguage('es');
    expect(formatJobRunEventSummary({
      ...commonSummary,
      qc: {
        evaluated: 286,
        passed: 282,
        flagged: 4,
        indeterminate: 0,
      },
    })).toBe(
      '3 dispositivos · 286 recibidas · 284 insertadas · 2 omitidas · CC: 282 aprobadas, 4 marcadas'
    );
    expect(formatJobRunEventSummary({
      ...commonSummary,
      reference_locations_failed: [
        { region: 'sao_paulo', location_id: '175911' },
      ],
    })).toContain(
      'No se pudo cargar la ubicación de referencia de AirGradient 175911 (São Paulo)'
    );
  });
});
