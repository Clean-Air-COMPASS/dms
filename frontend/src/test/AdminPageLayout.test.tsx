import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AdminPageLayout from '../components/AdminPageLayout';

describe('AdminPageLayout', () => {
  it('renders the standard page header by default', () => {
    render(
      <MemoryRouter>
        <AdminPageLayout
          title="Devices"
          description="Manage devices."
          breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Devices' }]}
        >
          <div>Body</div>
        </AdminPageLayout>
      </MemoryRouter>
    );

    expect(screen.getByRole('heading', { name: 'Devices' })).toBeInTheDocument();
    expect(screen.getByText('Manage devices.')).toBeInTheDocument();
    expect(screen.getByText('COMPASS')).toBeInTheDocument();
    expect(screen.getByText('Map')).toBeInTheDocument();
    expect(screen.getByText('Analytics')).toBeInTheDocument();
  });

  it('keeps the top toolbar while hiding the standard page header when requested', () => {
    render(
      <MemoryRouter>
        <AdminPageLayout title="Hidden Title" hidePageHeader>
          <div>Editor Body</div>
        </AdminPageLayout>
      </MemoryRouter>
    );

    expect(screen.queryByRole('heading', { name: 'Hidden Title' })).not.toBeInTheDocument();
    expect(screen.getByText('COMPASS')).toBeInTheDocument();
    expect(screen.getByText('Map')).toBeInTheDocument();
    expect(screen.getByText('Analytics')).toBeInTheDocument();
    expect(screen.getByText('Editor Body')).toBeInTheDocument();
  });
});
