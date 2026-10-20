import i18n from './i18n';

type JobRunSummary = Record<string, unknown> | null | undefined;

function count(summary: JobRunSummary, key: string): number {
  const value = summary?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function nestedCount(summary: JobRunSummary, parentKey: string, key: string): number {
  const nested = summary?.[parentKey];
  if (!nested || typeof nested !== 'object' || Array.isArray(nested)) return 0;
  return count(nested as Record<string, unknown>, key);
}

function hasCount(summary: JobRunSummary, key: string): boolean {
  const value = summary?.[key];
  return typeof value === 'number' && Number.isFinite(value);
}

function withReferenceLocationFailures(summary: JobRunSummary, text: string): string {
  const failures = summary?.reference_locations_failed;
  if (!Array.isArray(failures) || failures.length === 0) return text;
  const regionLabels: Record<string, string> = {
    new_york: i18n.t('events:referenceLocations.newYork'),
    sao_paulo: i18n.t('events:referenceLocations.saoPaulo'),
    metro_manila: i18n.t('events:referenceLocations.metroManila'),
  };
  const failureMessages = failures.flatMap((failure) => {
    if (!failure || typeof failure !== 'object' || Array.isArray(failure)) return [];
    const failureFields = failure as Record<string, unknown>;
    const regionCode = String(failureFields.region || '');
    const locationId = String(failureFields.location_id || '');
    if (!regionCode || !locationId) return [];
    return [i18n.t('events:jobRunSummary.referenceLocationFailed', {
      locationId,
      region: regionLabels[regionCode] || regionCode,
    })];
  });
  return failureMessages.length > 0
    ? `${text} · ${failureMessages.join(' · ')}`
    : text;
}

export function formatJobRunStatus(
  status: string | null | undefined,
  languageCode: string = i18n.resolvedLanguage || i18n.language,
): string {
  const normalizedStatus = (status || '').toLowerCase();
  const translate = i18n.getFixedT(languageCode, 'events');
  const statusLabels: Record<string, string> = {
    success: translate('jobRunStatus.success'),
    failed: translate('jobRunStatus.failed'),
    running: translate('jobRunStatus.running'),
    skipped: translate('jobRunStatus.skipped'),
    timeout: translate('jobRunStatus.timeout'),
    interrupted: translate('jobRunStatus.interrupted'),
  };
  if (statusLabels[normalizedStatus]) return statusLabels[normalizedStatus];
  return status || translate('jobRunStatus.neverRun');
}

function formatLegacyJobRunSummary(summary: JobRunSummary): string {
  if (!summary) return i18n.t('events:jobRunSummary.unavailable');
  const legacyResults = Array.isArray(summary.results) ? summary.results : [];
  const devicesProcessed = legacyResults.length;
  const measurementsInserted = nestedCount(summary, 'overall', 'insert')
    || nestedCount(summary, 'overall_totals', 'insert')
    || nestedCount(summary, 'measurements', 'insert');

  if (devicesProcessed === 0 && measurementsInserted === 0) {
    return i18n.t('events:jobRunSummary.unavailable');
  }

  if (measurementsInserted > 0) {
    return i18n.t('events:jobRunSummary.devicesAndImported', {
      devices: devicesProcessed,
      measurements: measurementsInserted,
    });
  }
  return i18n.t('events:jobRunSummary.noNewMeasurements', {
    devices: devicesProcessed,
  });
}

const countTranslationKeys = {
  devices: 'events:jobRunSummary.devices',
  devicesChecked: 'events:jobRunSummary.devicesChecked',
  devicesCreated: 'events:jobRunSummary.devicesCreated',
  sensorsCreated: 'events:jobRunSummary.sensorsCreated',
  received: 'events:jobRunSummary.received',
  inserted: 'events:jobRunSummary.inserted',
  updated: 'events:jobRunSummary.updated',
  skipped: 'events:jobRunSummary.skipped',
  qcPassed: 'events:jobRunSummary.qcPassed',
  qcFlagged: 'events:jobRunSummary.qcFlagged',
  qcIndeterminate: 'events:jobRunSummary.qcIndeterminate',
} as const;

function translatedCount(key: keyof typeof countTranslationKeys, value: number): string {
  return i18n.t(countTranslationKeys[key], { count: value });
}

/** Concise summary used beside the latest-import status on a Data Source. */
export function formatJobRunSummary(summary: JobRunSummary): string {
  if (!summary) return '—';
  if (!Object.prototype.hasOwnProperty.call(summary, 'devices_processed')) {
    return formatLegacyJobRunSummary(summary);
  }

  const devicesProcessed = count(summary, 'devices_processed');
  const devicesCreated = count(summary, 'devices_created');
  const sensorsCreated = count(summary, 'sensors_created');
  const measurementsInserted = count(summary, 'measurements_inserted');
  const measurementsUpdated = count(summary, 'measurements_updated');
  const measurementsSkipped = count(summary, 'measurements_skipped');

  if (devicesProcessed === 0 && devicesCreated === 0) {
    return withReferenceLocationFailures(summary, i18n.t('events:jobRunSummary.zeroDevices'));
  }

  const parts: string[] = [];
  if (devicesCreated > 0) parts.push(translatedCount('devicesCreated', devicesCreated));
  if (sensorsCreated > 0) parts.push(translatedCount('sensorsCreated', sensorsCreated));
  if (measurementsInserted > 0) parts.push(translatedCount('inserted', measurementsInserted));
  if (measurementsUpdated > 0) parts.push(translatedCount('updated', measurementsUpdated));
  if (measurementsSkipped > 0) parts.push(translatedCount('skipped', measurementsSkipped));

  if (parts.length === 0) {
    return withReferenceLocationFailures(summary, i18n.t('events:jobRunSummary.noNewMeasurements', {
      devices: devicesProcessed,
    }));
  }

  return withReferenceLocationFailures(summary, parts.join(' · '));
}

/** Operational summary used by Events, where received/update/QC detail matters. */
export function formatJobRunEventSummary(summary: JobRunSummary): string {
  if (!summary) return '—';
  if (!Object.prototype.hasOwnProperty.call(summary, 'devices_processed')) {
    return formatLegacyJobRunSummary(summary);
  }

  const devicesProcessed = count(summary, 'devices_processed');
  const devicesCreated = count(summary, 'devices_created');
  const sensorsCreated = count(summary, 'sensors_created');
  const measurementsReceived = count(summary, 'measurements_received');
  const measurementsInserted = count(summary, 'measurements_inserted');
  const measurementsUpdated = count(summary, 'measurements_updated');
  const measurementsSkipped = count(summary, 'measurements_skipped');

  if (devicesProcessed === 0 && devicesCreated === 0) {
    return withReferenceLocationFailures(summary, i18n.t('events:jobRunSummary.zeroDevices'));
  }

  const parts: string[] = [];
  if (devicesCreated > 0) {
    parts.push(translatedCount('devicesCreated', devicesCreated));
  } else if (
    measurementsReceived === 0
    && measurementsInserted === 0
    && measurementsUpdated === 0
  ) {
    parts.push(translatedCount('devicesChecked', devicesProcessed));
  } else {
    parts.push(translatedCount('devices', devicesProcessed));
  }
  if (sensorsCreated > 0) parts.push(translatedCount('sensorsCreated', sensorsCreated));

  if (hasCount(summary, 'measurements_received')) {
    parts.push(translatedCount('received', measurementsReceived));
  }
  if (measurementsInserted > 0 || measurementsReceived > 0) {
    parts.push(translatedCount('inserted', measurementsInserted));
  }
  if (measurementsUpdated > 0) parts.push(translatedCount('updated', measurementsUpdated));
  if (measurementsSkipped > 0) parts.push(translatedCount('skipped', measurementsSkipped));
  if (measurementsInserted === 0 && measurementsUpdated === 0) {
    parts.push(i18n.t('events:jobRunSummary.noNewMeasurementsOnly'));
  }

  const qcEvaluated = nestedCount(summary, 'qc', 'evaluated');
  if (qcEvaluated > 0) {
    const qcPassed = nestedCount(summary, 'qc', 'passed');
    const qcFlagged = nestedCount(summary, 'qc', 'flagged');
    const qcIndeterminate = nestedCount(summary, 'qc', 'indeterminate');
    const qcParts: string[] = [];
    if (qcPassed > 0 || qcFlagged > 0 || qcIndeterminate > 0) {
      qcParts.push(translatedCount('qcPassed', qcPassed));
    }
    if (qcFlagged > 0) qcParts.push(translatedCount('qcFlagged', qcFlagged));
    if (qcIndeterminate > 0) {
      qcParts.push(translatedCount('qcIndeterminate', qcIndeterminate));
    }
    if (qcParts.length > 0) {
      parts.push(i18n.t('events:jobRunSummary.qc', { outcomes: qcParts.join(', ') }));
    }
  }

  return withReferenceLocationFailures(summary, parts.join(' · '));
}
