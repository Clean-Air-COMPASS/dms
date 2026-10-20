import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import BuildInformation from '../admin/BuildInformation';
import { compareBuilds, frontendVersion, getBackendVersion } from '../buildIdentity';
import i18n from '../i18n';

vi.mock('../buildIdentity', async () => {
  const actual = await vi.importActual<typeof import('../buildIdentity')>('../buildIdentity');
  return {
    ...actual,
    frontendVersion: { application_version: '0.1.0', frontend: { commit_sha: 'a'.repeat(40), build_time_utc: '2026-10-18T20:00:00Z' } },
    getBackendVersion: vi.fn(),
  };
});

const backend = (sha: string | null) => ({
  application_version: '0.1.0',
  backend: { commit_sha: sha, build_time_utc: '2026-10-18T20:01:00Z' },
  environment: 'development' as const,
});

beforeEach(async () => {
  await i18n.changeLanguage('en');
  vi.mocked(getBackendVersion).mockReset();
  frontendVersion.frontend.commit_sha = 'a'.repeat(40);
});

describe('BuildInformation', () => {
  it('compares full SHAs and ignores timestamp differences', async () => {
    vi.mocked(getBackendVersion).mockResolvedValue(backend('a'.repeat(40)));
    render(<BuildInformation />);
    expect(await screen.findByText('Frontend and backend builds match')).toBeVisible();
    expect(screen.getByText('CompassAQ v0.1.0')).toBeVisible();
    expect(screen.getAllByText('a'.repeat(40))).toHaveLength(2);
    expect(screen.getByText('2026-10-18 20:00:00 UTC')).toBeVisible();
    expect(screen.getByText('2026-10-18 20:01:00 UTC')).toBeVisible();
    expect(screen.getByText('Development')).toBeVisible();
  });

  it('warns about different complete SHAs even when their prefixes match', async () => {
    vi.mocked(getBackendVersion).mockResolvedValue(backend(`${'a'.repeat(39)}b`));
    render(<BuildInformation />);
    expect(await screen.findByText('Frontend and backend builds differ')).toBeVisible();
  });

  it('shows the application version when local build SHAs are unknown', async () => {
    frontendVersion.frontend.commit_sha = null;
    vi.mocked(getBackendVersion).mockResolvedValue(backend(null));
    render(<BuildInformation />);
    await waitFor(() => expect(screen.getAllByText('Unknown')).toHaveLength(2));
    expect(screen.getByText('CompassAQ v0.1.0')).toBeVisible();
    expect(screen.getByText('Build comparison unavailable')).toBeVisible();
    expect(compareBuilds({ commit_sha: null, build_time_utc: null }, backend(null).backend)).toBe('unknown');
    expect(compareBuilds({ commit_sha: null, build_time_utc: null }, backend('a'.repeat(40)).backend)).toBe('unknown');
  });

  it('keeps frontend identity available while loading and after backend failure, then retries', async () => {
    vi.mocked(getBackendVersion).mockRejectedValueOnce(new Error('unreachable')).mockResolvedValueOnce(backend('a'.repeat(40)));
    render(<BuildInformation />);
    expect(screen.getByText('CompassAQ v0.1.0')).toBeVisible();
    expect(screen.getByText(frontendVersion.frontend.commit_sha!)).toBeVisible();
    expect(await screen.findByRole('alert')).toHaveTextContent('Backend build information could not be loaded.');
    expect(screen.getByText('CompassAQ v0.1.0')).toBeVisible();
    expect(screen.getAllByText('Unavailable')).toHaveLength(3);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Frontend and backend builds match')).toBeVisible();
  });

  it('localizes labels and status in Spanish', async () => {
    await i18n.changeLanguage('es');
    vi.mocked(getBackendVersion).mockResolvedValue(backend('b'.repeat(40)));
    render(<BuildInformation />);
    expect(await screen.findByText('Las compilaciones de la interfaz y del servidor son diferentes')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Información de compilación' })).toBeVisible();
    expect(screen.getByText('CompassAQ v0.1.0')).toBeVisible();
    expect(screen.getByText('Entorno')).toBeVisible();
    await waitFor(() => expect(screen.getByText('Desarrollo')).toBeVisible());
  });
});
