import { test, expect, type Page } from '@playwright/test';
import type { Map as MapLibreMap } from 'maplibre-gl';
import { readFile } from 'node:fs/promises';

// Read the mounted map ref in tests only; camera assertions exercise real
// MapLibre/WebGL without adding a debug API to the application.
async function camera(page: Page, action: 'state' | 'jump' | 'pan' = 'state', longitude = 0, zoom = 0) {
  return page.locator('.map-canvas').evaluate((element, args) => {
    type Hook = { memoizedState?: {current?: MapLibreMap}; next?: Hook };
    type Fiber = { memoizedState?: Hook; return?: Fiber };
    const key=Object.keys(element).find(key=>key.startsWith('__reactFiber'))!;
    let fiber=(element as unknown as Record<string,Fiber>)[key];
    let map: MapLibreMap | undefined;
    while(fiber && !map) {
      let hook=fiber.memoizedState;
      while(hook && !map) {
        const current=hook.memoizedState?.current;
        if(current && typeof current.getCenter==='function') map=current;
        hook=hook.next;
      }
      fiber=fiber.return!;
    }
    if(!map) throw new Error('Mounted MapLibre ref not found');
    if(args.action==='jump') map.jumpTo({center:[args.longitude,0],zoom:args.zoom});
    if(args.action==='pan') map.panBy([args.longitude,0],{duration:0});
    return {lng:map.getCenter().lng,lat:map.getCenter().lat,zoom:map.getZoom(),
      worldCopies:map.getRenderWorldCopies(),bounds:map.getBounds().toArray(),loaded:map.loaded()};
  },{action,longitude,zoom});
}

for(const language of ['en','es']) for(const width of [1440,1200,390]) {
  test(`Map AQI export, search width and real world wrapping ${language} ${width}`,async ({page},testInfo)=>{
    page.setDefaultTimeout(20000);
    await page.setViewportSize({width,height:900});
    await page.addInitScript(lang=>{
      localStorage.setItem('compassaq.language',lang);
      navigator.geolocation.getCurrentPosition=()=>{};
    },language);
    const device={device_id:901,name:'Synthetic antimeridian station',friendly_name:'Synthetic antimeridian station',
      longitude:179,latitude:0,sensor_count:1,timezone:'UTC'};
    const longLocation=language==='en' ? 'San Luis Obispo, California, United States' : 'London, Greater London, United Kingdom';
    await page.route(/\/api\/devices(?:\?.*)?$/,route=>route.fulfill({json:[device]}));
    await page.route('**/api/devices/901/sensors**',route=>route.fulfill({json:[]}));
    await page.route('**/api/air-quality-index/*/latest**',route=>{
      const url=new URL(route.request().url());
      const standard=url.pathname.split('/').at(-2)!;
      const categorical=standard==='eea_european';
      const result={device_id:901,device_name:device.name,device_friendly_name:'Estación "Niño", µg/m³',
        latitude:0,longitude:179,source_name:'Other',standard_code:standard,
        product_code:categorical ? null : url.searchParams.get('product_code'), result_kind:categorical?'categorical':'numeric',
        numeric_value:categorical?null:42,category_code:categorical?'fair':'good',category_label:categorical?'Fair':'Good',
        dominant_pollutants:['pm25'], observed_at:'2026-10-07T12:00:00Z',calculation_status:categorical?null:'calculated',
        eligibility_status:'eligible',coverage_status:categorical?null:'complete',exclusion_reasons:[],sensor_provenance:[],
        coverage:{coverage_status:'partial',available_pollutants:['pm25'],missing_pollutants:['no2'],ineligible_pollutants:[],missing_or_ineligible_pollutants:['no2']},
        pollutant_results:[{parameter_code:'pm25',category_code:'fair',category_label:'Fair',eligibility_status:'eligible',numeric_value:null}]};
      return route.fulfill({json:{standard_code:standard,product_code:result.product_code,count:2,results:[result,
        {...result,device_id:902,device_name:'Synthetic unavailable station',device_friendly_name:null,longitude:-179,numeric_value:null,
          category_code:null,category_label:null,calculation_status:'unavailable',eligibility_status:'ineligible',exclusion_reasons:['insufficient_data'],dominant_pollutants:[],
          pollutant_results:[{parameter_code:'pm25',numeric_value:null,category_code:null,category_label:null,eligibility_status:'ineligible',exclusion_reason:'insufficient_data'}]}]}});
    });
    let release!:()=>void;
    const slow=new Promise<void>(resolve=>{release=resolve;});
    await page.route('**/api/geocode/autocomplete**',async route=>{
      const text=new URL(route.request().url()).searchParams.get('text');
      if(text==='Slow') {await slow; return route.fulfill({status:502,json:{detail:'Synthetic failure'}});}
      return route.fulfill({json:{cached:false,results:[{place_id:'synthetic-location',name:text==='Antimeridian'?'Synthetic antimeridian location':longLocation,
        lat:text==='Antimeridian'?0:35.28,lon:text==='Antimeridian'?-179.5:-120.66,result_type:'city'}]}});
    });
    await page.goto('/map');
    await expect(page.locator('.maplibregl-canvas')).toBeVisible();
    await expect(page.locator('.map-loading')).toBeHidden();
    const openControls=async()=>{if(width===390) await page.getByRole('button',{name:/^(Map controls|Controles del mapa)$/}).click();};
    const closeControls=async()=>{if(width===390) await page.getByRole('button',{name:/^(Close controls|Cerrar controles)$/}).click();};
    await openControls();
    const search=page.getByRole('combobox',{name:/^(Search location|Buscar ubicación)$/});
    const capture=async(name:string)=>{
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      const toolbar=page.locator(width===390?'.map-controls-surface':'.overlay-controls');
      expect(await toolbar.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
      await page.screenshot({path:testInfo.outputPath(`${name}.png`),animations:'disabled'});
    };
    await capture('search-empty');
    if(width>390) expect((await search.boundingBox())!.width).toBeGreaterThanOrEqual(280);
    await search.fill(longLocation);
    await expect(page.getByRole('option',{name:longLocation})).toBeVisible();
    await capture('search-typed');
    await page.getByRole('option',{name:longLocation}).click();
    await expect(search).toHaveValue(longLocation);
    await expect.poll(async()=>(await camera(page)).lng).toBeCloseTo(-120.66,1);
    await capture('search-selected');
    const selectedWidth=(await search.boundingBox())!.width;
    expect(selectedWidth).toBeGreaterThanOrEqual(width===390?300:280);
    await testInfo.attach('search-width.json',{body:JSON.stringify({language,width,selectedWidth}),contentType:'application/json'});
    await search.press('Tab');
    await expect(page.getByRole('button',{name:/^(Clear search|Borrar búsqueda)$/})).toBeFocused();
    await capture('search-clear-focus');
    await page.getByRole('button',{name:/^(Reset view|Restablecer vista)$/}).click();
    await expect.poll(async()=>(await camera(page)).lng).toBeCloseTo(0,1);
    await search.fill('Slow');
    await expect(page.locator('.location-search [role=status]')).toContainText(language==='en'?'Searching':'Buscando');
    await capture('search-loading'); release();
    await expect(page.locator('.location-search [role=status]')).toContainText(language==='en'?'failed':'No se pudo');
    expect(await page.locator('.location-search-error').evaluate(el=>
      el.getBoundingClientRect().bottom<=el.parentElement!.getBoundingClientRect().bottom)).toBe(true);
    await capture('search-error');
    await page.getByRole('button',{name:/^(Clear search|Borrar búsqueda)$/}).click();
    await expect(search).toHaveValue('');
    await page.locator('.map-layer-control select').selectOption('aqi');
    await expect(page.locator('.map-loading')).toBeHidden();
    await page.locator('.aqi-product-control select').selectOption('eea_european.pm25.hourly');
    await page.locator('.map-source-control select').selectOption('other');
    await expect(page.locator('.map-loading')).toBeHidden();
    await page.locator('.map-download summary').click();
    const downloadButton=page.getByRole('button',{name:/^(Download CSV|Descargar CSV)$/});
    await expect(downloadButton).toHaveAccessibleDescription(/San|latest|último/);
    await downloadButton.scrollIntoViewIfNeeded();
    await expect(downloadButton).toBeInViewport();
    await capture('aqi-export');
    const requestPromise=page.waitForRequest(request=>request.url().includes('/eea_european/latest'));
    const downloadPromise=page.waitForEvent('download');
    await downloadButton.click();
    const request=new URL((await requestPromise).url());
    expect([...request.searchParams]).toEqual([['product_code','eea_european.pm25.hourly'],['external_api_name','other'],['all_results','true']]);
    const bytes=await readFile((await (await downloadPromise).path())!);
    expect([...bytes.subarray(0,3)]).toEqual([239,187,191]);
    expect(bytes.toString('utf8')).toContain('categorical,,Fair,');
    expect(bytes.toString('utf8')).toContain('Synthetic unavailable station');
    expect(bytes.toString('utf8')).toContain('ineligible,partial,insufficient_data');
    await page.locator('.map-download summary').click();
    await closeControls();
    const global=await camera(page,'jump',0,0);
    expect(global.worldCopies).toBe(true);
    await expect.poll(async()=>(await camera(page)).loaded).toBe(true);
    await capture('world-wrapped');
    await camera(page,'jump',179,2);
    await camera(page,'pan',600);
    // MapLibre normalizes the center after crossing the antimeridian. At zoom
    // 2, 600 pixels advances 600 / (512 * 4) * 360 degrees without clamping.
    expect((await camera(page)).lng).toBeCloseTo(-75.53125,2);
    await camera(page,'pan',-1800);
    expect((await camera(page)).lng).toBeCloseTo(-31.9375,2);
    await camera(page,'jump',539,6);
    await expect(page.locator('[data-map-marker-key^="european-"]')).toHaveCount(2);
    const marker=page.locator('[data-map-marker-key="european-901"]');
    await expect(marker).toBeInViewport();
    await marker.click();
    await expect(page.locator('.slide-out-panel')).toContainText('Estación');
    await capture('repeated-copy-result');
    await page.keyboard.press('Escape');
    await openControls();
    await search.fill('Antimeridian');
    await page.getByRole('option',{name:'Synthetic antimeridian location'}).click();
    await expect.poll(async()=>Math.abs((await camera(page)).lng)).toBeCloseTo(179.5,1);
    await page.getByRole('button',{name:/^(Reset view|Restablecer vista)$/}).click();
    await expect.poll(async()=>(await camera(page)).lng).toBeCloseTo(0,1);
    await closeControls();
    await capture('reset-after-pan');
    // Physical dragging still reaches MapLibre rather than an overlay, also
    // at the narrow layout used by the mobile controls.
    const start=(await camera(page)).lng;
    await page.mouse.move(width/2,220);
    await page.mouse.down();
    await page.mouse.move(width/2-120,220,{steps:12});
    await page.mouse.up();
    await expect.poll(async()=>(await camera(page)).lng).not.toBe(start);
    await openControls();
    await page.locator('.map-layer-control select').selectOption('measurements');
    await expect(page.locator('.map-loading')).toBeHidden();
    expect((await search.boundingBox())!.width).toBeGreaterThanOrEqual(width===390?300:280);
    await capture('measurement-toolbar');
  });
}
