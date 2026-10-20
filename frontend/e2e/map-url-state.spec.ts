import { expect, test } from '@playwright/test';

for (const width of [1440, 390]) {
  test(`Map query state belongs only to Map at ${width}px`, async ({ page }, testInfo) => {
    page.setDefaultTimeout(15000);
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => localStorage.setItem('compassaq.language', 'en'));
    const rewrites: string[] = [];
    await page.exposeFunction('recordMapUrlRewrite', (url: string) => rewrites.push(url));
    await page.addInitScript(() => {
      const replace = history.replaceState.bind(history);
      history.replaceState = (data, unused, url) => {
        void (window as unknown as { recordMapUrlRewrite: (url: string) => void }).recordMapUrlRewrite(String(url));
        replace(data, unused, url);
      };
    });
    await page.goto('/');
    await expect(page.locator('.landing-page')).toBeVisible();
    await expect(page).toHaveURL(/\/$/);
    await page.screenshot({ path: testInfo.outputPath('home.png'), fullPage: true });
    await page.getByRole('link', { name: 'Open Map', exact: true }).click();
    await expect(page.locator('.map-canvas')).toBeVisible();
    await expect(page).toHaveURL(/\/map$/);
    if (width === 390) await page.getByRole('button', { name: 'Map controls', exact: true }).click();
    await expect(page.getByLabel('Layer', { exact: true })).toHaveValue('devices');
    await expect(page.getByLabel('Time window presets')).toHaveCount(0);
    await page.getByLabel('Parameter', { exact: true }).selectOption('pm25');
    await expect(page).toHaveURL(/parameter=pm25/);
    if (width === 390) await page.getByRole('button', { name: 'Close controls' }).click();
    await expect(page.locator('.map-loading')).toBeHidden();
    await page.screenshot({ path: testInfo.outputPath('map.png'), fullPage: true });
    const deepLink = page.url();
    for (let index = 0; index < 2; index++) {
      await page.getByRole('link', { name: /sign in/i }).click();
      await page.getByRole('link', { name: /back.*home/i }).click();
      await expect(page.locator('.landing-page')).toBeVisible();
      await expect(page).toHaveURL(/\/$/);
      await page.goBack();
      await page.goBack();
      await expect(page).toHaveURL(deepLink);
      await page.goForward();
      await page.goForward();
      await expect(page).toHaveURL(/\/$/);
      await page.goBack();
      await page.goBack();
    }
    await page.goto('/?mode=devices&display_mode=measurements&recency=24h&utm_source=test#about');
    await expect(page).toHaveURL(/\/\?utm_source=test#about$/);
    await page.goto('/map?mode=devices&display_mode=eea_european');
    if (width === 390) await page.getByRole('button', { name: 'Map controls', exact: true }).click();
    await expect(page.getByLabel('Layer', { exact: true })).toHaveValue('aqi');
    await expect(page.getByLabel('AQI product', { exact: true })).toHaveValue('eea_european.overall.hourly');
    await expect(page).toHaveURL(/product_code=eea_european.overall.hourly/);
    await page.reload();
    if (width === 390) await page.getByRole('button', { name: 'Map controls', exact: true }).click();
    await expect(page.getByLabel('AQI product', { exact: true })).toHaveValue('eea_european.overall.hourly');
    const rewriteCount = rewrites.length;
    await page.waitForTimeout(1000);
    expect(rewrites).toHaveLength(rewriteCount);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

