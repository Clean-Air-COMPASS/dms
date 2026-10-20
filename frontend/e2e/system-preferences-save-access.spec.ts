import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';

import { mockAdministration } from './fixtures/administration';

const scenarios = [
  { language: 'en', width: 1440, title: 'System Preferences', apiKey: 'Geoapify API Key', timezone: 'System timezone', save: 'Save changes', saved: 'System preferences updated.' },
  { language: 'en', width: 390, title: 'System Preferences', apiKey: 'Geoapify API Key', timezone: 'System timezone', save: 'Save changes', saved: 'System preferences updated.' },
  { language: 'es', width: 1440, title: 'Preferencias del sistema', apiKey: 'Clave Geoapify API', timezone: 'Zona horaria del sistema', save: 'Guardar cambios', saved: 'Preferencias del sistema actualizadas.' },
  { language: 'es', width: 390, title: 'Preferencias del sistema', apiKey: 'Clave Geoapify API', timezone: 'Zona horaria del sistema', save: 'Guardar cambios', saved: 'Preferencias del sistema actualizadas.' },
] as const;

for (const scenario of scenarios) {
  test(`System Preferences save access ${scenario.language} ${scenario.width}`, async ({ page }) => {
    await page.setViewportSize({ width: scenario.width, height: scenario.width === 390 ? 844 : 1000 });
    const state = await mockAdministration(page, scenario.language);
    await page.goto('/admin/system-preferences');

    await expect(page.getByRole('heading', { name: scenario.title, level: 1 })).toBeVisible();
    const saveButtons = page.getByRole('button', { name: scenario.save, exact: true });
    const topSave = page.locator('.admin-page-actions').getByRole('button', { name: scenario.save, exact: true });
    const bottomSave = page.locator('.preferences-save-actions').getByRole('button', { name: scenario.save, exact: true });
    await expect(saveButtons).toHaveCount(2);
    await expect(topSave).toBeVisible();
    await expect(bottomSave).toBeVisible();

    const timezone = page.getByLabel(scenario.timezone, { exact: true });
    await timezone.focus();
    await page.keyboard.press('Tab');
    await expect(bottomSave).toBeFocused();
    await expect(bottomSave).toHaveCSS('position', 'static');

    await timezone.selectOption('Asia/Manila');
    await bottomSave.click();
    await expect.poll(() => state.preferences.system_timezone).toBe('Asia/Manila');
    await expect(page.getByText(scenario.saved, { exact: true })).toHaveCount(1);

    await page.getByLabel(scenario.apiKey, { exact: true }).fill('access-check-key');
    await topSave.click();
    await expect.poll(() => state.preferences.geoapify_api_key).toBe('access-check-key');
    await expect(page.getByText(scenario.saved, { exact: true })).toHaveCount(1);

    for (const button of [topSave, bottomSave]) {
      const touchTarget = await button.evaluate((element) => ({
        height: element.getBoundingClientRect().height,
        minHeight: getComputedStyle(element).minHeight,
      }));
      expect(touchTarget.minHeight, 'Save actions must have a 44px CSS touch target').toBe('44px');
      expect(touchTarget.height, 'Save actions must have a 44px touch target').toBeGreaterThanOrEqual(43.99);
    }

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    mkdirSync('../artifacts/system-preferences-save-access', { recursive: true });
    await page.screenshot({
      path: `../artifacts/system-preferences-save-access/${scenario.language}-${scenario.width}.png`,
      fullPage: true,
    });
  });
}
