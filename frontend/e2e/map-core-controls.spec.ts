import {expect, test} from '@playwright/test';
import {readFile} from 'node:fs/promises';

for (const language of ['en','es']) for (const width of [1440,390]) {
  test(`Map search isolation, reset and CSV scope ${language} ${width}`, async ({page},testInfo) => {
    await page.setViewportSize({width,height:900});
    await page.addInitScript(lang => {
      localStorage.setItem('compassaq.language',lang);
      // An unanswered permission prompt used to prevent map creation entirely.
      navigator.geolocation.getCurrentPosition = () => {};
    },language);
    let release!: () => void;
    const pending = new Promise<void>(resolve => {release=resolve;});
    await page.route('**/api/geocode/autocomplete**',async route => {
      const text = new URL(route.request().url()).searchParams.get('text');
      if(text==='Slow') {await pending; await route.fulfill({status:502,json:{detail:'Synthetic geocoder failure'}});}
      else await route.fulfill({json:{cached:false,results:text==='Empty' ? [] : [{place_id:'qa-london',name:'London',formatted:'London',lat:51.5,lon:-0.12,result_type:'city'}]}});
    });
    await page.route('**/api/measurements/pm10/latest**', async route => {
      const url = new URL(route.request().url());
      if (!url.searchParams.has('offset')) return route.continue();
      await route.fulfill({json:[{measurement_id:1,sensor_id:1,parameter:'pm10',parameter_name:'PM10',
        value:10,unit:'µg/m³',observed_at:'2026-01-01T00:00:00Z',
        device:{device_id:1,name:'Synthetic export fixture',network:'Other'}}]});
    });
    await page.goto('/map');
    await expect(page.locator('.maplibregl-canvas')).toBeVisible();
    if(width===390) await page.getByRole('button',{name:/^(Map controls|Controles del mapa)$/}).click();
    const search = page.getByRole('combobox',{name:/^(Search location|Buscar ubicación)$/});
    await search.fill('Slow');
    await expect(page.locator('.location-search [role=status]')).toContainText(language==='en'?'Searching':'Buscando');
    for(const layer of ['aqi','measurements','devices']) {
      await page.locator('.map-layer-control select').selectOption(layer);
      await expect(page.locator('.map-loading')).toBeHidden();
      await expect(page.locator('.map-layer-control select')).toHaveValue(layer);
      await expect(page.locator('.maplibregl-canvas')).toHaveCount(1);
    }
    release();
    await expect(page.locator('.location-search [role=status]')).toContainText(language==='en'?'failed':'No se pudo');
    await search.press('Tab');
    await expect(page.getByRole('button',{name:/^(Clear search|Borrar búsqueda)$/})).toBeFocused();
    await page.locator('.map-layer-control select').selectOption('aqi');
    await expect(page.locator('.map-loading')).toBeHidden();
    await page.locator('.aqi-product-control select').selectOption('eea_european.overall.hourly');
    await expect(page.locator('.map-loading')).toBeHidden();
    await expect(page).toHaveURL(/product_code=eea_european.overall.hourly/);
    await page.getByRole('button',{name:/^(Reset view|Restablecer vista)$/}).click();
    expect(await page.locator('.map-download').count()).toBe(1);
    await search.fill('Empty');
    await expect(page.locator('.location-search [role=status]')).toContainText(language==='en'?'No matches':'No se encontraron');
    await page.screenshot({path:testInfo.outputPath('search-empty.png')});
    await search.fill('London');
    await page.getByRole('option',{name:'London',exact:true}).click();
    await expect(search).toHaveValue('London');
    for(const layer of ['devices','measurements']) {
      await page.locator('.map-layer-control select').selectOption(layer);
      await expect(page.locator('.map-loading')).toBeHidden();
      await page.getByRole('button',{name:/^(Reset view|Restablecer vista)$/}).click();
    }
    await page.locator('.map-parameter-control select').selectOption('pm10');
    await expect(page.locator('.map-loading')).toBeHidden();
    await page.locator('.map-source-control select').selectOption('other');
    await expect(page.locator('.map-loading')).toBeHidden();
    await page.locator('.map-download summary').click();
    const explanation=page.locator('.map-download-panel p');
    await expect(explanation).not.toContainText('100');
    await expect(explanation).toContainText('PM10');
    await expect(explanation).toContainText('Other');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    for(const dialog of await page.locator('dialog[open]').all()) expect(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
    await page.screenshot({path:testInfo.outputPath('export-scope.png'),fullPage:true});
    await page.getByRole('button',{name:/^(Download CSV|Descargar CSV)$/}).scrollIntoViewIfNeeded();
    await page.screenshot({path:testInfo.outputPath('export-action.png')});
    const downloadPromise=page.waitForEvent('download');
    const requestPromise=page.waitForRequest(request=>request.url().includes('/measurements/pm10/latest')&&!request.url().includes('all_results'));
    await page.getByRole('button',{name:/^(Download CSV|Descargar CSV)$/}).click();
    const download=await downloadPromise;
    const request=await requestPromise;
    const url=new URL(request.url());
    expect(url.searchParams.get('external_api_name')).toBe('other');
    expect(url.searchParams.has('bbox')).toBe(false);
    expect(url.searchParams.has('since')).toBe(false);
    const csv=await readFile((await download.path())!,'utf8');
    expect(csv.replace(/^\uFEFF/,'').split('\n')[0].trim()).toBe('Measurement ID,Sensor ID,External Sensor ID,Parameter,Parameter Name,Value,Unit,Observed At (UTC),Device ID,Device Name,Latitude,Longitude,Data Provider,Contributor,Contributor URL,Provider URL,License,License URL');
    expect(csv).toContain('pm10');
    if(width===390) await page.getByRole('button',{name:/^(Close controls|Cerrar controles)$/}).click();
    await page.screenshot({path:testInfo.outputPath('reset-map.png')});
  });
}
