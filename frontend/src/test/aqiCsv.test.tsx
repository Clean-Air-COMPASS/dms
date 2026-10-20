import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import QuickDownload from '../components/QuickDownload';
import { buildAqiCsv } from '../aqiCsv';
import type { AirQualityIndexCollection, DeviceAirQualityIndexResult } from '../airQualityIndex';
import i18n from '../i18n';

const header = 'Device ID,Device Name,Friendly Name,Latitude,Longitude,Data Provider,AQI Standard,AQI Product,Result Kind,AQI Value,AQI Category,Dominant Pollutants,Observed / Represented Time,Calculation Status,Eligibility Status,Location Coverage Status,Exclusion Reasons,Missing Pollutants';
const result: DeviceAirQualityIndexResult = {
  device_id: 7, device_name: 'Estación "Niño", µg/m³', device_friendly_name: 'Área Norte',
  latitude: 0, longitude: 179.5, source_name: 'Other', standard_code: 'us_epa',
  product_code: 'us_epa.pm25.nowcast', result_kind: 'numeric', numeric_value: 42,
  category_label: 'Good', dominant_pollutants: ['pm25'], observed_at: '2026-10-07T12:00:00Z',
  calculation_status: 'calculated', eligibility_status: 'eligible', coverage_status: 'complete',
  exclusion_reasons: [], pollutant_results: [],
  methodology_version: 'test', device_timezone: 'UTC', category_code: 'good', sensor_provenance: [],
  coverage: {coverage_status:'complete',available_pollutants:['pm25'],missing_pollutants:[],
    ineligible_pollutants:[],missing_or_ineligible_pollutants:[],display_qualification:'not_evaluated'},
};
const collection = {standard_code:'us_epa', product_code:'us_epa.pm25.nowcast', result_kind:'numeric',
  count:1, results:[result]} as AirQualityIndexCollection;

function response(body: unknown) { return {ok:true, json:async()=>body} as Response; }
async function blobBytes() {
  const blob = vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob;
  return new Promise<Uint8Array>(resolve => {
    const reader=new FileReader(); reader.onload=()=>resolve(new Uint8Array(reader.result as ArrayBuffer)); reader.readAsArrayBuffer(blob);
  });
}
function control() { return <QuickDownload mode="aqi" standardCode="us_epa" productCode="us_epa.pm25.nowcast" source="other" />; }

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(collection)));
  Object.defineProperty(URL,'createObjectURL',{configurable:true,value:vi.fn(()=> 'blob:aqi')});
  Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()});
  vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
  vi.spyOn(console,'error').mockImplementation(()=>{});
});
afterEach(async () => {vi.restoreAllMocks(); vi.unstubAllGlobals(); await i18n.changeLanguage('en');});

describe('latest Map AQI CSV', () => {
  it('exports every result with selected standard/product/source, BOM and independently specified CSV values', async () => {
    const rows=Array.from({length:235},(_,index)=>({...result,device_id:index+7}));
    vi.mocked(fetch).mockResolvedValue(response({...collection,count:rows.length,results:rows}));
    render(control());
    await userEvent.click(screen.getByRole('button',{name:'Download CSV'}));
    expect(fetch).toHaveBeenCalledExactlyOnceWith('/api/air-quality-index/us_epa/latest?product_code=us_epa.pm25.nowcast&external_api_name=other&all_results=true');
    const bytes=await blobBytes();
    expect([...bytes.slice(0,3)]).toEqual([239,187,191]);
    const lines=new TextDecoder().decode(bytes).split('\n');
    expect(lines).toHaveLength(236);
    expect(lines[0]).toBe(header);
    expect(lines[1]).toBe('7,"Estación ""Niño"", µg/m³",Área Norte,0,179.5,Other,us_epa,us_epa.pm25.nowcast,numeric,42,Good,pm25,2026-10-07T12:00:00Z,calculated,eligible,complete,,');
  });

  it('retains unavailable numeric rows with blank AQI, backend statuses, reasons and escaped newlines', () => {
    const csv=buildAqiCsv({...collection,results:[{...result,device_name:'Two\nlines',numeric_value:null,
      category_label:null,dominant_pollutants:[],calculation_status:'unavailable',eligibility_status:'ineligible',
      coverage_status:'none',exclusion_reasons:['insufficient_data']}]},'us_epa.pm25.nowcast');
    expect(csv).toBe(header+'\n7,"Two\nlines",Área Norte,0,179.5,Other,us_epa,us_epa.pm25.nowcast,numeric,,,,2026-10-07T12:00:00Z,unavailable,ineligible,none,insufficient_data,');
  });

  it.each([null,'pm25'])('selects EEA overall or pollutant backend categories with no numeric invention: %s', async parameterCode => {
    const eeaResult={...result,standard_code:'eea_european',product_code:null,result_kind:'categorical',numeric_value:null,
      category_label:'Poor',dominant_pollutants:['no2'],calculation_status:null,coverage_status:null,
      coverage:{coverage_status:'partial'},pollutant_results:[{parameter_code:'pm25',numeric_value:null,
        category_label:'Fair',eligibility_status:'eligible',exclusion_reason:null}]};
    vi.mocked(fetch).mockResolvedValue(response({...collection,standard_code:'eea_european',product_code:null,results:[eeaResult]}));
    const product=`eea_european.${parameterCode || 'overall'}.hourly`;
    render(<QuickDownload mode="aqi" standardCode="eea_european" productCode={product} aqiParameterCode={parameterCode} />);
    await userEvent.click(screen.getByRole('button',{name:'Download CSV'}));
    expect(fetch).toHaveBeenCalledExactlyOnceWith(`/api/air-quality-index/eea_european/latest?product_code=${product}&all_results=true`);
    const csv=new TextDecoder().decode(await blobBytes());
    expect(csv).toContain(parameterCode ? ',categorical,,Fair,,2026-10-07T12:00:00Z,,eligible,partial,' : ',categorical,,Poor,no2,2026-10-07T12:00:00Z,,eligible,partial,');
  });

  it('retains missing EEA pollutant results without borrowing the overall category', () => {
    const eea={...collection,standard_code:'eea_european',results:[{...result,standard_code:'eea_european',
      result_kind:'categorical',numeric_value:null,category_label:'Poor',pollutant_results:[],
      coverage_status:null,coverage:{...result.coverage,coverage_status:'partial',missing_pollutants:['pm25']}}]} as AirQualityIndexCollection;
    const fields=buildAqiCsv(eea,'eea_european.pm25.hourly','pm25').split('\n')[1];
    expect(fields).toContain(',eea_european.pm25.hourly,categorical,,,,2026-10-07T12:00:00Z,,,partial,,pm25');
    expect(fields).not.toContain('Poor');
  });

  it.each(['duplicate','count','product','empty','http'])('rejects %s responses without producing a partial file and allows retry', async failure => {
    const body=failure==='duplicate' ? {...collection,count:2,results:[result,result]}
      : failure==='count' ? {...collection,count:2}
      : failure==='product' ? {...collection,product_code:'wrong'}
      : failure==='empty' ? {...collection,count:0,results:[]} : collection;
    vi.mocked(fetch).mockResolvedValueOnce(failure==='http' ? {ok:false,status:502} as Response : response(body));
    render(control());
    await userEvent.click(screen.getByRole('button',{name:'Download CSV'}));
    expect(screen.getByRole('alert')).toHaveTextContent('No file was downloaded');
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button',{name:'Download CSV'}));
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
  });

  it('announces loading and prevents duplicate clicks while the complete request is pending', async () => {
    let release!: (value:Response)=>void;
    vi.mocked(fetch).mockReturnValue(new Promise(resolve=>{release=resolve;}));
    render(control());
    await userEvent.click(screen.getByRole('button',{name:'Download CSV'}));
    const busy=screen.getByRole('button',{name:'Downloading CSV'});
    expect(busy).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Downloading CSV');
    await userEvent.click(busy);
    expect(fetch).toHaveBeenCalledOnce();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    release(response(collection));
    await waitFor(()=>expect(URL.createObjectURL).toHaveBeenCalledOnce());
  });

  it.each(['en','es'])('associates the translated scope disclosure with the action in %s', async language => {
    await i18n.changeLanguage(language);
    const explanation=i18n.t('map:app.text.aqiDownloadExplanation',{product:'PM2.5 NowCast',source:'Other'});
    render(<QuickDownload mode="aqi" explanation={explanation} />);
    await userEvent.click(screen.getByText(i18n.t('map:app.actions.csvExport')));
    expect(screen.getByRole('button',{name:i18n.t('analytics:quickDownload.text.downloadCsv')})).toHaveAccessibleDescription(explanation);
    expect(explanation).toContain('PM2.5 NowCast'); expect(explanation).toContain('Other');
    expect(explanation).toContain(language==='en' ? 'Analytics' : 'Análisis');
    expect(explanation).toContain(language==='en' ? 'unavailable' : 'no disponibles');
    expect(explanation).toContain(language==='en' ? 'does not limit' : 'no limita');
  });
});
