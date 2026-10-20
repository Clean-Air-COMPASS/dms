import { act, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import LandingPage from '../LandingPage';
import i18n from '../i18n';

describe('LandingPage partner section', () => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage('en'));
  });

  it('uses local official logos and current partner details', () => {
    render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>,
    );

    expect(screen.queryByRole('link', { name: 'About COMPASS' })).not.toBeInTheDocument();
    expect(screen.getByText('Mission partners & seed funding')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Natural Resources Defense Council' })).toHaveAttribute(
      'src',
      expect.stringContaining('nrdc-logo'),
    );
    expect(screen.getByRole('img', { name: 'Spheros Environmental' })).toHaveAttribute(
      'src',
      expect.stringContaining('spheros-environmental-logo'),
    );
    expect(screen.getByRole('link', { name: 'Spheros Environmental' })).toHaveAttribute(
      'href',
      'https://spherosenv.com/',
    );
    expect(screen.queryByText('&amp;')).not.toBeInTheDocument();
  });
});
