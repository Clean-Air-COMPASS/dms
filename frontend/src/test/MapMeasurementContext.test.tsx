import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import MapMeasurementContext from '../components/MapMeasurementContext';
import i18n from '../i18n';

afterEach(() => { cleanup(); void i18n.changeLanguage('en'); });

describe('Map scientific context', () => {
  it('uses result averaging metadata ahead of native resolution and shows an exact UTC time', () => {
    render(<MapMeasurementContext resultAggregation="1h" nativeAggregation="2m" observedAt="2026-09-05T09:30:12-07:00" isValid={false} />);
    expect(screen.getByText('1-hour average')).toBeVisible();
    expect(screen.getByText('Invalid measurement')).toBeVisible();
    const time = document.querySelector('time')!;
    expect(time.dateTime).toBe('2026-09-05T16:30:12.000Z');
    expect(time).toHaveTextContent('16:30:12 UTC');
    expect(screen.getByText('Observed at (UTC)')).toBeVisible();
  });

  it('shows native averaging metadata and explicit valid QC text when available', () => {
    render(<MapMeasurementContext nativeAggregation="2m" isValid />);
    expect(screen.getByText('2-minute')).toBeVisible();
    expect(screen.getByText('Valid measurement')).toBeVisible();
  });

  it('does not fabricate absent metadata or display an invalid timestamp', () => {
    render(<MapMeasurementContext observedAt="invalid" />);
    expect(screen.getAllByText('Not provided')).toHaveLength(3);
    expect(document.querySelector('time')).toBeNull();
  });

  it('localizes the context and QC text in Spanish', async () => {
    await i18n.changeLanguage('es');
    render(<MapMeasurementContext isValid={false} />);
    expect(screen.getByText('Estado de QC')).toBeVisible();
    expect(screen.getByText(i18n.t('map:mapLibreMap.tooltips.invalidMeasurement'))).toBeVisible();
  });

  it.each(['en', 'es'])('distinguishes rolling evaluation, interval and source freshness in %s', async (language) => {
    await i18n.changeLanguage(language);
    render(<MapMeasurementContext resultAggregation="rolling_24h" nativeAggregation="2m" isRolling
      observedAt="2026-10-09T04:50:00Z" intervalStartedAt="2026-10-08T04:50:00Z"
      intervalEndedAt="2026-10-09T04:50:00Z" latestSourceObservedAt="2026-10-09T04:00:00Z" />);
    expect(screen.getByText(language === 'en' ? 'Calculated at (UTC)' : 'Calculado el (UTC)')).toBeVisible();
    expect(screen.getByText(language === 'en' ? 'Rolling window (UTC)' : 'Ventana móvil (UTC)')).toBeVisible();
    const source = screen.getByText(language === 'en' ? 'Latest source observation (UTC)' : 'Última observación de origen (UTC)');
    expect(source.nextElementSibling?.querySelector('time')).toHaveAttribute('datetime', '2026-10-09T04:00:00.000Z');
    expect(screen.queryByText(language === 'en' ? 'Observed at (UTC)' : 'Observado el (UTC)')).not.toBeInTheDocument();
    expect(document.querySelectorAll('time')).toHaveLength(4);
  });

  it('does not substitute evaluation time for absent source freshness', () => {
    render(<MapMeasurementContext isRolling observedAt="2026-10-09T04:50:00Z" />);
    expect(screen.getByText('Latest source observation (UTC)').nextElementSibling).toHaveTextContent('Not provided');
  });
});
