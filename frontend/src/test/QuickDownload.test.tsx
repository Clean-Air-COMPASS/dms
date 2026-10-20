import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { buildDeviceCsv, buildMeasurementCsv } from '../quickDownloadCsv';
import QuickDownload from '../components/QuickDownload';
import i18n from '../i18n';


describe('buildMeasurementCsv', () => {
  it('preserves a measurement identifier above the signed 32-bit range', () => {
    const csv = buildMeasurementCsv([
      {
        measurement_id: 2_147_483_648,
        sensor_id: 7,
        external_sensor_id: 'stream-7',
        parameter: 'pm25',
        value: 12.5,
        unit: 'µg/m³',
        observed_at: '2026-08-12T12:00:00+00:00',
        device: {
          device_id: 3,
          name: 'High ID device',
          latitude: 38.5,
          longitude: -122.8,
          network: 'Test',
        },
      },
    ]);

    expect(csv.split('\n')[1].split(',')[0]).toBe('2147483648');
  });

  it('exports canonical parameter code, localized name, unit, source, and stream identity', async () => {
    await i18n.changeLanguage('es');
    const csv = buildMeasurementCsv([{
      measurement_id: 9,
      sensor_id: 7,
      external_sensor_id: '175911:atmp',
      parameter: 'temperature',
      parameter_name: 'Temperature',
      value: 17.7,
      unit: '°C',
      observed_at: '2026-09-03T05:38:00Z',
      device: {
        device_id: 3,
        friendly_name: 'AirGradient Friendly Name',
        name: 'AirGradient 175911',
        network: 'AirGradient',
        data_attribution: {
          acquisition_path: 'airgradient_public_reference',
          data_provider_name: 'AirGradient',
          hardware_provider_name: 'AirGradient',
          contributor_name: 'Community Lab',
          contributor_url: 'https://example.org/community-lab',
          provider_url: 'https://www.airgradient.com',
          license_code: 'CC-BY-SA-4.0',
          license_url: 'https://creativecommons.org/licenses/by-sa/4.0/',
        },
      },
    }]);

    expect(csv.split('\n')[0]).toBe([
      'Measurement ID', 'Sensor ID', 'External Sensor ID', 'Parameter', 'Parameter Name',
      'Value', 'Unit', 'Observed At (UTC)', 'Device ID', 'Device Name', 'Latitude',
      'Longitude', 'Data Provider', 'Contributor', 'Contributor URL', 'Provider URL',
      'License', 'License URL',
    ].join(','));
    expect(csv).toContain('9,7,175911:atmp,temperature,Temperature,17.7,°C,2026-09-03T05:38:00.000Z,3,AirGradient Friendly Name');
    expect(csv).toContain('AirGradient,Community Lab,https://example.org/community-lab,https://www.airgradient.com,CC-BY-SA-4.0,https://creativecommons.org/licenses/by-sa/4.0/');
    expect(csv).not.toContain('Nombre del parámetro');
    expect(csv).not.toContain('Acquisition Path');
    expect(csv).not.toContain('Hardware Provider');
    await i18n.changeLanguage('en');
  });
});

describe('QuickDownload', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        measurement_id: 1,
        sensor_id: 2,
        parameter: 'pm25',
        value: 12.5,
        unit: 'µg/m³',
        observed_at: '2026-08-12T12:00:00Z',
        device: { device_id: 3, name: 'Test device', latitude: 38.5, longitude: -122.8, network: 'Test' },
      }],
    }));

    Object.defineProperty(window.URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:test-csv'),
    });
    Object.defineProperty(window.URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('renders an accessible icon-only CSV control and preserves the download request', async () => {
    const user = userEvent.setup();
    render(<QuickDownload parameter="pm25" aggregation="1h" iconOnly />);

    const button = screen.getByRole('button', { name: 'Download CSV' });
    expect(button).toHaveAttribute('title', 'Download CSV');
    expect(button).toHaveClass('quick-download-btn--icon-only');
    expect(button).not.toHaveTextContent('Download CSV');
    expect(button.querySelector('svg')).toBeInTheDocument();

    await user.click(button);

    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/measurements/pm25/latest?aggregation=1h&limit=100&offset=0'));
    expect(window.URL.createObjectURL).toHaveBeenCalledOnce();
  });
  it.each(['en', 'es'])('explains Map scope before exporting unchanged CSV in %s', async language => {
    await i18n.changeLanguage(language);
    const explanation = i18n.t('map:app.text.downloadExplanation', {parameter:'PM2.5', aggregation:'1h'});
    render(<QuickDownload parameter="pm25" aggregation="1h" explanation={explanation} />);
    const details = document.querySelector('details')!;
    expect(details).not.toHaveAttribute('open');
    await userEvent.click(screen.getByText(i18n.t('map:app.actions.csvExport')));
    expect(details).toHaveAttribute('open');
    const button=screen.getByRole('button', {name:i18n.t('analytics:quickDownload.text.downloadCsv')});
    expect(button).toHaveAccessibleDescription(explanation);
    expect(explanation).not.toContain('100');
    expect(explanation).toContain('PM2.5');
    expect(explanation).toContain('1h');
    await userEvent.click(button);
    const request = new URL(String(vi.mocked(fetch).mock.calls[0][0]),'http://localhost');
    expect(request.pathname).toMatch(/measurements\/pm25\/latest$/);
    expect([...request.searchParams]).toEqual([['aggregation','1h'],['limit','100'],['offset','0']]);
    await i18n.changeLanguage('en');
  });

  it('exports a filtered device inventory with UTF-8 and stable headings', async () => {
    const devices = [{device_id: 3, name: 'Estación "Niño", µg/m³', friendly_name: 'Área Norte',
      external_id: 'site-3', network: 'Other', latitude: 0, longitude: -3, timezone: 'Europe/Madrid', sensor_count: 2}];
    vi.mocked(fetch).mockResolvedValue({ok:true, json:async () => devices} as Response);
    render(<QuickDownload mode="devices" parameter="pm25" source="other" aggregation="1h" />);
    await userEvent.click(screen.getByRole('button', {name:'Download CSV'}));
    expect(fetch).toHaveBeenCalledExactlyOnceWith(expect.stringContaining('/devices?external_api_name=other&parameter=pm25'));
    const blob = vi.mocked(window.URL.createObjectURL).mock.calls[0][0] as Blob;
    const text = await new Promise<string>(resolve => {const reader = new FileReader(); reader.onload=()=>resolve(String(reader.result)); reader.readAsText(blob);});
    expect(text).toBe('Device ID,Device Name,Friendly Name,External Device ID,Data Provider,Latitude,Longitude,Timezone,Sensor Count\n3,"Estación ""Niño"", µg/m³",Área Norte,site-3,Other,0,-3,Europe/Madrid,2');
    const link = vi.mocked(HTMLAnchorElement.prototype.click).mock.instances[0] as HTMLAnchorElement;
    expect(link.download).toMatch(/^compassaq-devices-\d{4}-\d{2}-\d{2}\.csv$/);
  });

  it.each([0, 1, 99, 100, 235])('retrieves all %i measurement rows with filters on every page', async count => {
    const measurements = Array.from({length:count}, (_,index) => ({measurement_id:index+1, sensor_id:index+1,
      parameter:'pm25', value:index, unit:'µg/m³', observed_at:'2026-09-03T05:38:00Z'}));
    vi.mocked(fetch).mockImplementation(async input => {
      const url = new URL(String(input),'http://localhost');
      expect(url.pathname).toMatch(/\/measurements\/pm25\/latest$/);
      expect(url.searchParams.get('external_api_name')).toBe('other');
      expect(url.searchParams.get('aggregation')).toBe('1h');
      expect(url.searchParams.get('limit')).toBe('100');
      expect(url.searchParams.has('bbox')).toBe(false);
      expect(url.searchParams.has('since')).toBe(false);
      const offset=Number(url.searchParams.get('offset'));
      return {ok:true,json:async () => measurements.slice(offset,offset+100)} as Response;
    });
    render(<QuickDownload parameter="pm25" aggregation="1h" source="other" />);
    await userEvent.click(screen.getByRole('button', {name:'Download CSV'}));
    expect(fetch).toHaveBeenCalledTimes(Math.floor(count/100)+1);
    if(count===0) {
      expect(window.URL.createObjectURL).not.toHaveBeenCalled();
      expect(screen.getByRole('alert')).toHaveTextContent('No records match');
      return;
    }
    const blob = vi.mocked(window.URL.createObjectURL).mock.calls[0][0] as Blob;
    const bytes = await new Promise<ArrayBuffer>(resolve => {const reader=new FileReader(); reader.onload=()=>resolve(reader.result as ArrayBuffer); reader.readAsArrayBuffer(blob);});
    expect(Array.from(new Uint8Array(bytes).slice(0,3))).toEqual([239,187,191]);
    const lines=new TextDecoder().decode(bytes).split('\n');
    expect(lines[0]).toBe('Measurement ID,Sensor ID,External Sensor ID,Parameter,Parameter Name,Value,Unit,Observed At (UTC),Device ID,Device Name,Latitude,Longitude,Data Provider,Contributor,Contributor URL,Provider URL,License,License URL');
    expect(lines).toHaveLength(count+1);
    expect(new Set(lines.slice(1).map(line=>line.split(',')[1])).size).toBe(count);
  });

  it('announces loading, blocks duplicate clicks, and downloads no partial file after a later page fails', async () => {
    let fail!: (response: Response) => void;
    const pending=new Promise<Response>(resolve=>{fail=resolve;});
    vi.mocked(fetch).mockResolvedValueOnce({ok:true,json:async()=>Array.from({length:100},(_,index)=>({sensor_id:index+1}))} as Response).mockReturnValueOnce(pending);
    vi.spyOn(console,'error').mockImplementation(()=>{});
    render(<QuickDownload parameter="pm25" />);
    await userEvent.click(screen.getByRole('button', {name:'Download CSV'}));
    const button=screen.getByRole('button', {name:'Downloading CSV'});
    expect(button).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Downloading CSV');
    await userEvent.click(button);
    expect(fetch).toHaveBeenCalledTimes(2);
    fail({ok:false,status:502} as Response);
    await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent('No file was downloaded'));
    expect(window.URL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.getByRole('button',{name:'Download CSV'})).toBeEnabled();
  });

  it('rejects repeated sensor identities rather than saving an inconsistent export', async () => {
    const rows=Array.from({length:100},(_,index)=>({sensor_id:index+1}));
    vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>rows} as Response);
    vi.spyOn(console,'error').mockImplementation(()=>{});
    render(<QuickDownload parameter="pm25" />);
    await userEvent.click(screen.getByRole('button',{name:'Download CSV'}));
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(window.URL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('No file was downloaded');
  });

});

describe('buildDeviceCsv', () => {
  it('keeps unavailable public API fields blank and omits internal fields', () => {
    const csv=buildDeviceCsv([{device_id:1,name:'Sin ubicación',sensor_count:0,created_at:'private'}]);
    expect(csv).toBe('Device ID,Device Name,Friendly Name,External Device ID,Data Provider,Latitude,Longitude,Timezone,Sensor Count\n1,Sin ubicación,,,,,,,0');
    expect(csv).not.toContain('private');
  });
});
