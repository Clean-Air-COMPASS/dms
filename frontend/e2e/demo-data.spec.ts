import { expect, test, type Page } from '@playwright/test';

// Browser-only API state: no existing database or live provider is modified.
async function mockSources(page: Page, language: string, setup: boolean) {
  const demo = { external_api_id: 4, provider_code: 'demo', name: 'Demo Data', enabled: setup, requires_credential: false, has_api_key: false, is_configured: true, is_runnable: setup, runnable_reason: setup ? 'ready' : 'disabled', is_builtin: true, can_delete: false };
  const sources = ['PurpleAir', 'OpenAQ', 'AirGradient'].map((name, index) => ({ external_api_id: index + 1, provider_code: name.toLowerCase(), name, enabled: false, requires_credential: true, has_api_key: false, is_configured: false, is_runnable: false, runnable_reason: 'disabled' }));
  const state = { complete: !setup, demo, failSave: false, writes: [] as unknown[] };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, '');
    if (state.failSave && ['/setup/data-source', '/admin/external_apis/4'].includes(path) && route.request().method() !== 'GET') {
      await route.fulfill({ status: 500, json: {} });
      return;
    }
    let body: unknown = [];
    if (path === '/health/readiness') body = { status: 'ready' };
    else if (path === '/setup/status') body = { is_setup_required: !state.complete, has_users: true, default_language_code: language };
    else if (path === '/setup/data-sources') body = { data_sources: [...sources, demo] };
    else if (path === '/setup/data-source') {
      const payload = route.request().postDataJSON();
      state.writes.push(payload);
      if (payload.external_api_id === 4) Object.assign(demo, payload);
      body = { success: true };
    } else if (path === '/setup/complete') { state.complete = true; body = { success: true }; }
    else if (path === '/auth/refresh') body = { access_token: 'fixture-session' };
    else if (path === '/auth/me') body = { user_id: 'review-admin', email: 'admin@example.org', roles: ['admin'], scopes: ['users:write'], preferred_language_code: language, system_default_language_code: language };
    else if (path === '/admin/external_apis') body = [demo, ...sources];
    else if (path === '/admin/external_apis/4') {
      if (route.request().method() === 'PUT') {
        const payload = route.request().postDataJSON();
        expect(Object.keys(payload)).toEqual(['enabled']);
        state.writes.push(payload);
        Object.assign(demo, payload, { is_runnable: payload.enabled, runnable_reason: payload.enabled ? 'ready' : 'disabled' });
      }
      body = demo;
    }
    await route.fulfill({ json: body });
  });
  return state;
}

async function capture(page: Page, name: string) {
  await page.locator('.setup-wizard-overlay').evaluateAll(elements => elements.forEach(el => el.scrollTo(0, 0)));
  await page.screenshot({ path: `../artifacts/demo-data/${name}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const overlay = page.locator('.setup-wizard-overlay');
  if (await overlay.count()) {
    expect(await overlay.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await overlay.evaluate(el => el.scrollTo(0, el.scrollHeight));
    await page.screenshot({ path: `../artifacts/demo-data/${name}-actions.png`, fullPage: true });
  }
}

for (const language of ['en', 'es']) for (const width of [1440, 1280, 390]) {
  test(`Demo setup persistence ${language} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ colorScheme: 'dark' });
    const state = await mockSources(page, language, true);
    await page.goto('/');
    const toggle = page.getByRole('checkbox', { name: language === 'en' ? 'Enable Demo Data' : 'Habilitar Demo Data' });
    await expect(toggle).toBeChecked();
    await expect(toggle).toHaveCSS('color-scheme', 'light');
    await expect(toggle).toHaveCSS('accent-color', 'rgb(6, 71, 137)');
    const demoCard = page.locator('.setup-source-card').filter({ hasText: 'Demo Data' });
    await expect(page.locator('.setup-source-card strong')).toHaveText(['Demo Data', 'PurpleAir', 'OpenAQ', 'AirGradient']);
    await expect(demoCard.locator('input[type=text]')).toHaveCount(0);
    await expect(page.locator('.setup-source-api-key-input')).toHaveCount(3);
    await page.keyboard.press('Tab');
    await toggle.focus();
    await expect(toggle).toBeFocused();
    expect(await toggle.evaluate(el => getComputedStyle(el).outlineStyle)).not.toBe('none');
    await capture(page, `setup-${language}-${width}-enabled`);
    await toggle.press('Space');
    await expect(toggle).not.toBeChecked();
    await capture(page, `setup-${language}-${width}-disabled`);
    await page.getByRole('button', { name: language === 'en' ? 'Save Sources & Continue' : 'Guardar fuentes y continuar' }).click();
    await page.getByRole('button', { name: /←/ }).click();
    await expect(toggle).not.toBeChecked();
    await page.reload();
    await expect(toggle).not.toBeChecked();
    await page.getByRole('button', { name: language === 'en' ? 'Skip for Now →' : 'Saltar por ahora →' }).click();
    await page.getByRole('button', { name: language === 'en' ? 'Skip for Now →' : 'Saltar por ahora →' }).click();
    await page.getByRole('button', { name: language === 'en' ? 'Complete Setup & Start Using Platform' : 'Complete la configuración y comience a usar la plataforma' }).click();
    await expect.poll(() => state.complete).toBe(true);
    expect(state.demo.enabled).toBe(false);
    expect(state.writes.filter(item => (item as { external_api_id?: number }).external_api_id === 4)).toEqual([{ external_api_id: 4, enabled: false }]);
  });
  test(`Demo Admin controls ${language} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const state = await mockSources(page, language, false);
    await page.goto('/admin/sources');
    const link = page.getByRole('link', { name: /Demo Data/ });
    await expect(link).toBeVisible();
    await capture(page, `admin-list-${language}-${width}-disabled`);
    await link.click();
    const toggle = page.getByRole('checkbox', { name: language === 'en' ? 'Enable Demo Data' : 'Habilitar Demo Data' });
    await expect(toggle).not.toBeChecked();
    await expect(page.locator('.api-key-input')).toHaveCount(0);
    await page.keyboard.press('Tab');
    await toggle.focus();
    expect(await toggle.evaluate(el => getComputedStyle(el).outlineStyle)).not.toBe('none');
    await capture(page, `admin-detail-${language}-${width}-disabled`);
    await toggle.press('Space');
    await page.getByRole('button', { name: language === 'en' ? 'Save changes' : 'Guardar cambios', exact: true }).click();
    await expect.poll(() => state.demo.enabled).toBe(true);
    await capture(page, `admin-detail-${language}-${width}-enabled`);
    await toggle.uncheck();
    await page.getByRole('button', { name: language === 'en' ? 'Save changes' : 'Guardar cambios', exact: true }).click();
    await expect.poll(() => state.demo.enabled).toBe(false);
    await page.reload();
    await expect(toggle).not.toBeChecked();
  });
}

for (const setup of [true, false]) {
  test(`Demo save failure is recoverable in ${setup ? 'setup' : 'Admin'}`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 1000 });
    const state = await mockSources(page, 'en', setup);
    await page.goto(setup ? '/' : '/admin/sources/4');
    const toggle = page.getByRole('checkbox', { name: 'Enable Demo Data' });
    await expect(toggle).toBeVisible();
    state.failSave = true;
    await toggle.click();
    if (!setup) await page.getByRole('button', { name: 'Save changes', exact: true }).click();
    await expect(page.getByRole('alert')).toBeVisible();
    expect(state.demo.enabled).toBe(setup);
    await capture(page, `${setup ? 'setup' : 'admin'}-save-error-en-390`);
    state.failSave = false;
    if (setup) await toggle.click();
    else await page.getByRole('button', { name: 'Save changes', exact: true }).click();
    await expect.poll(() => state.demo.enabled).toBe(!setup);
  });
}
