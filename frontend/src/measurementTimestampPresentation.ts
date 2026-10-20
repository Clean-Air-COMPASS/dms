import i18n from './i18n';

export function getMeasurementTimestampRoleLabel(
  timestampSemantics: string | null | undefined,
): string | null {
  if (timestampSemantics === 'observation_instant') {
    return i18n.t('analytics:sensorChart.timestampRoles.observation_instant');
  }
  if (timestampSemantics === 'interval_start') {
    return i18n.t('analytics:sensorChart.timestampRoles.interval_start');
  }
  if (timestampSemantics === 'interval_end') {
    return i18n.t('analytics:sensorChart.timestampRoles.interval_end');
  }
  if (timestampSemantics === 'provider_received_at') {
    return i18n.t('analytics:sensorChart.timestampRoles.provider_received_at');
  }
  return null;
}
