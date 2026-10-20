import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import DataAttribution from '../components/DataAttribution';
import i18n from '../i18n';


describe('DataAttribution', () => {
  it.each([
    'https://example.org/data?api_key=synthetic-secret',
    'https://example.org/data#token=synthetic-secret',
    'https://user:synthetic-secret@example.org/data',
    'javascript:alert("synthetic-secret")',
  ])('omits unsafe credential-bearing or non-HTTP links: %s', url => {
    const { container } = render(<DataAttribution value={{
      acquisition_path: 'unspecified', data_provider_name: 'PurpleAir', hardware_provider_name: null,
      provider_url: url, contributor_name: 'Synthetic Organization', contributor_url: url,
      license_code: 'CC-BY-4.0', license_url: url, license_share_alike: false,
    }} />);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(container.innerHTML).not.toContain('synthetic-secret');
    expect(container).toHaveTextContent('PurpleAir');
    expect(container).toHaveTextContent('Synthetic Organization');
  });

  it('does not render an empty section for metadata without displayable fields', () => {
    const { container } = render(<DataAttribution value={{
      acquisition_path: 'unspecified', data_provider_name: null, hardware_provider_name: null,
      provider_url: null, contributor_name: null, contributor_url: null,
      license_code: null, license_url: null, license_share_alike: null,
    }} />);
    expect(container).toBeEmptyDOMElement();
  });

  afterEach(async () => {
    await act(async () => {
      await i18n.changeLanguage('en');
    });
  });

  it('presents direct AirGradient contributor and share-alike license links', () => {
    render(<DataAttribution value={{
      acquisition_path: 'airgradient_public_reference',
      data_provider_name: 'AirGradient',
      hardware_provider_name: 'AirGradient',
      provider_url: 'https://www.airgradient.com',
      contributor_name: 'Community Lab',
      contributor_url: 'https://example.org/community-lab',
      license_code: 'CC-BY-SA-4.0',
      license_url: 'https://creativecommons.org/licenses/by-sa/4.0/',
      license_share_alike: true,
    }} />);

    expect(screen.getByRole('complementary', { name: 'Data attribution' })).toHaveTextContent('Data provided by AirGradient');
    expect(screen.getByRole('link', { name: 'Community Lab' })).toHaveAttribute('href', 'https://example.org/community-lab');
    expect(screen.getByRole('link', { name: 'CC-BY-SA-4.0' })).toHaveAttribute('href', 'https://creativecommons.org/licenses/by-sa/4.0/');
  });

  it('distinguishes AirGradient hardware transported through OpenAQ in Spanish', async () => {
    await act(async () => {
      await i18n.changeLanguage('es');
    });
    render(<DataAttribution value={{
      acquisition_path: 'openaq',
      data_provider_name: 'OpenAQ',
      hardware_provider_name: 'AirGradient',
      provider_url: 'https://openaq.org',
      contributor_name: 'Manila Observatory',
      contributor_url: null,
      license_code: 'CC-BY-4.0',
      license_url: 'https://creativecommons.org/licenses/by/4.0/',
      license_share_alike: false,
    }} />);

    expect(screen.getByRole('complementary', { name: 'Atribución de datos' })).toHaveTextContent('Datos proporcionados por AirGradient a través de OpenAQ');
    expect(screen.getByText(/Manila Observatory/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'CC-BY-4.0' })).toHaveAttribute('href', 'https://creativecommons.org/licenses/by/4.0/');
  });

  it('does not infer a public license for authenticated owner data', () => {
    render(<DataAttribution value={{
      acquisition_path: 'airgradient_authenticated',
      data_provider_name: 'AirGradient',
      hardware_provider_name: 'AirGradient',
      provider_url: 'https://www.airgradient.com',
      contributor_name: null,
      contributor_url: null,
      license_code: null,
      license_url: null,
      license_share_alike: null,
    }} />);

    expect(screen.getByText(/no public-data license is inferred/i)).toBeInTheDocument();
  });
});
