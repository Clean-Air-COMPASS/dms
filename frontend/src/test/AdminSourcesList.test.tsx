import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import AdminSourcesList from '../AdminSourcesList';

vi.mock('../auth', () => ({
  useAuth: () => ({
    isAuthenticated: false,
    user: null,
    logout: vi.fn(),
    isLoading: false,
  }),
}));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    listExternalAPIs: vi.fn().mockResolvedValue([
      {
        external_api_id: 8,
        name: 'AirGradient',
        base_url: 'https://airgradient.example',
        enabled: true,
        is_builtin: true,
        can_delete: false,
        is_runnable: true,
        runnable_reason: 'ready',
        device_count: 0,
        latest_import: {
          job_run_id: 10,
          job_schedule_id: 4,
          task: 'airgradient_import',
          status: 'success',
          started_at: '2026-08-16T14:00:00Z',
          summary: { devices_processed: 3, measurements_inserted: 12 },
        },
      },
      { external_api_id: 9, name: 'Custom Source', base_url: 'https://custom.example', enabled: false, is_builtin: false, can_delete: true, is_runnable: false, runnable_reason: 'disabled' },
    ]),
  };
});

describe('AdminSourcesList', () => {
  it('links View actions to the canonical ID-only detail route', async () => {
    render(
      <MemoryRouter>
        <AdminSourcesList />
      </MemoryRouter>
    );

    const airGradientLink = await screen.findByRole('link', { name: 'Open AirGradient view' });
    const customSourceLink = await screen.findByRole('link', { name: 'Open Custom Source view' });
    expect(airGradientLink).toHaveAttribute('href', '/admin/sources/8');
    expect(customSourceLink).toHaveAttribute('href', '/admin/sources/9');
    expect(screen.getByText('Success')).toBeInTheDocument();
    expect(screen.getByText('Never run')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Delete' })).toHaveLength(1);
  });
});
