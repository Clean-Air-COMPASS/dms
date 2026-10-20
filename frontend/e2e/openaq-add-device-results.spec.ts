import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { mockAdministration } from './fixtures/administration';

const result = {
  device: {
    external_id: 'openaq-demo-456',
    name: 'Demo fixture — Coastal Air Lab',
    external_api_id: 1,
    latitude: -33.4489,
    longitude: -70.6693,
    timezone: 'America/Santiago',
  },
  sensors: [
    { sensor_id: 761, name: 'Fine particulate matter', parameter_code: 'pm25', parameter_display: 'PM2.5', unit: 'µg/m³', exists: false },
    { sensor_id: 762, name: 'Ozone', parameter_code: 'o3', parameter_display: 'O₃', unit: 'µg/m³', exists: false },
  ],
  metadata: {
    locality: 'Harbor District',
    country_name: 'Chile',
    country_code: 'CL',
    provider_name: 'Pacific Monitoring Network',
    owner_name: 'National Environment Agency',
    is_monitor: true,
    is_mobile: false,
    datetime_first_utc: '2024-01-15T00:00:00Z',
    datetime_last_utc: '2026-09-21T18:00:00Z',
    latest_value: 18.75,
    latest_datetime_utc: '2026-09-21T18:00:00Z',
    coverage_percent: 96.4,
    observed_count: 8432,
    expected_count: 8750,
  },
  already_exists: false,
};

const labels = {
  en: {
    columns: ['Select', 'Name', 'Location', 'Provider', 'Coordinates', 'Sensors', 'Data Range', 'Type'],
    search: 'Search',
    proceed: 'Proceed',
    noSelection: 'No devices selected',
  },
  es: {
    columns: ['Seleccionar', 'Nombre', 'Ubicación', 'Proveedor', 'Coordenadas', 'Sensores', 'Rango de datos', 'Tipo'],
    search: 'Buscar',
    proceed: 'Proceder',
    noSelection: 'No hay dispositivos seleccionados',
  },
} as const;

for (const language of ['en', 'es'] as const) {
  for (const width of [1440, 390]) {
    test(`OpenAQ location results use matching labels in ${language} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1050 });
      await mockAdministration(page, language);
      await page.route('**/api/admin/devices/openaq/lookup', (route) => route.fulfill({ json: { locations: [result] } }));

      await page.goto('/admin/devices/new/openaq');
      const inputs = page.locator('.bbox-fields-grid input');
      for (const [index, value] of ['-73', '-34', '-70', '-33'].entries()) {
        await inputs.nth(index).fill(value);
      }
      await page.getByRole('button', { name: labels[language].search, exact: true }).click();
      await page.getByRole('button', { name: labels[language].proceed, exact: true }).click();

      const table = page.getByRole('table');
      const row = table.locator('tbody tr').first();
      await expect(row).toBeVisible();
      expect(await table.locator('thead th').allTextContents()).toEqual(labels[language].columns);

      const cells = row.locator('td');
      expect(await cells.evaluateAll((elements) => elements.map((cell) => cell.getAttribute('data-label')))).toEqual(labels[language].columns);
      expect(await cells.evaluateAll((elements) => elements.map((cell) => cell.getAttribute('headers')))).toEqual(
        await table.locator('thead th').evaluateAll((elements) => elements.map((header) => header.id)),
      );
      await expect(cells.nth(2)).toContainText('Harbor District');
      await expect(cells.nth(2)).toContainText('Chile');
      await expect(cells.nth(3)).toContainText('Pacific Monitoring Network');
      await expect(cells.nth(3)).toContainText('National Environment Agency');
      await expect(cells.nth(5)).toContainText('PM25');
      await expect(cells.nth(5)).toContainText('O3');
      await expect(cells.nth(6)).toContainText('2024');
      await expect(cells.nth(6)).toContainText('2026');
      await expect(cells.nth(7)).toContainText('Monitor');

      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      expect(await page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(width);

      if (width === 390) {
        const visibleLabels = await cells.evaluateAll((elements) => elements.map((cell) => getComputedStyle(cell, '::before').content));
        expect(visibleLabels).toEqual(labels[language].columns.map((label) => `"${label}"`));
      }

      const deviceCheckbox = row.locator('input[type="checkbox"]').first();
      await expect(deviceCheckbox).toBeChecked();
      await deviceCheckbox.focus();
      await expect(deviceCheckbox).toBeFocused();
      await page.keyboard.press('Space');
      await expect(deviceCheckbox).not.toBeChecked();
      await expect(page.locator('.selection-summary')).toContainText(labels[language].noSelection);
      await page.keyboard.press('Space');
      await expect(deviceCheckbox).toBeChecked();

      const artifactDirectory = `../artifacts/openaq-add-device/${language}-${width}`;
      mkdirSync(artifactDirectory, { recursive: true });
      await page.screenshot({ path: `${artifactDirectory}/results.png`, fullPage: true });
    });
  }
}
