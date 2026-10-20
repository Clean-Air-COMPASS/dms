import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import QcStatusBadge from './QcStatusBadge';
import { unitSymbol } from './presentation';
import type { QcSensorSearchItem } from './types';

export default function QcSensorSearchResult({ sensor }: { sensor: QcSensorSearchItem }) {
  const { t } = useTranslation('qualityControl');
  const hasAdvancedQc = sensor.advanced_override_count > 0;
  let status = t('sensors.search.statusInherited');
  let tone: 'recommended' | 'custom' | 'neutral' = 'recommended';
  if (sensor.has_overrides && hasAdvancedQc) {
    status = t('sensors.search.statusCustomWithAdvanced');
    tone = 'custom';
  } else if (sensor.has_overrides) {
    status = t('sensors.search.statusCustom');
    tone = 'custom';
  } else if (hasAdvancedQc) {
    status = t('sensors.search.statusAdvanced');
    tone = 'neutral';
  }

  const identifier = sensor.external_sensor_id
    ? t('sensors.search.externalIdentifier', { identifier: sensor.external_sensor_id })
    : t('sensors.search.internalIdentifier', { identifier: sensor.sensor_id });

  return (
    <Link
      className="qc-sensor-result"
      to={`/admin/qc/sensors/${sensor.sensor_id}`}
      aria-label={t('sensors.search.openSensor', {
        device: sensor.device_name,
        parameter: sensor.parameter.display_name,
      })}
    >
      <div className="qc-sensor-result-identity">
        <strong>{sensor.device_name}</strong>
        <span>
          {sensor.parameter.display_name} · {sensor.manual_data_source_name || sensor.data_source.name}
          {sensor.unit ? ` · ${unitSymbol(sensor.unit)}` : ''}
        </span>
        <small>{identifier}</small>
      </div>
      <QcStatusBadge tone={tone}>{status}</QcStatusBadge>
    </Link>
  );
}
