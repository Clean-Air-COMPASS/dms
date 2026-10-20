import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import MapEmptyState from '../components/MapEmptyState';

describe('MapEmptyState', () => {
  it.each(['devices', 'measurements', 'aqi'] as const)('uses the shared accessible area/filter state for %s', layer => {
    render(<MapEmptyState layer={layer} />);
    expect(screen.getByTestId('map-empty-state')).toHaveAttribute('role', 'status');
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByRole('heading')).toHaveTextContent(/No .* found/);
    expect(screen.getByText(/in this area/)).toBeVisible();
    expect(screen.getByText('Explore another area or change the filters.')).toBeVisible();
    expect(screen.queryByText(/time range/i)).not.toBeInTheDocument();
  });
});
