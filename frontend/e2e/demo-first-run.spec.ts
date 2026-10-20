import { execFileSync } from 'node:child_process';
import { expect, test } from '@playwright/test';

// Dedicated disposable Compose project only; never run against a normal stack.
const acceptanceUrl = 'http://127.0.0.1:28480';
const apiContainer = 'compassaq-demo-first-run-api-1';
const enabled = process.env.DEMO_CLEAN_INSTALL_ACCEPTANCE === '1';
test.skip(!enabled, 'Requires the isolated demo-acceptance Compose project');

function python(code: string) {
  return execFileSync('docker', ['exec', apiContainer, 'python', '-c', code], { encoding: 'utf8' }).trim();
}

for (const language of ['en', 'es']) for (const width of [1440, 390]) for (const demoEnabled of [true, false]) {
  test(`clean Demo ${demoEnabled ? 'enabled' : 'disabled'} ${language} ${width}`, async ({ page, baseURL }) => {
    expect(baseURL).toBe(acceptanceUrl);
    // The named project's DB is disposable. A new schema has no installed
    // revision, so the real migrations exercise genuine clean-install defaults.
    python(`
from db import engine
from sqlalchemy import text
import subprocess, sys
with engine.begin() as connection:
    connection.execute(text('DROP SCHEMA public CASCADE'))
    connection.execute(text('CREATE SCHEMA public'))
subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True, capture_output=True)
`);
    await page.setViewportSize({ width, height: 1000 });
    await page.addInitScript(lang => localStorage.setItem('compassaq.language', lang), language);
    const spanish = language === 'es';
    await page.goto('/');
    await page.getByRole('button', { name: spanish ? 'Continuar' : 'Continue', exact: true }).click();
    await page.locator('#admin-email').fill('demo-review@example.org');
    await page.locator('#admin-password').fill('SampleReview2026!Strong');
    await page.locator('#admin-confirm-password').fill('SampleReview2026!Strong');
    await page.locator('button[type=submit]').click();
    await page.getByRole('button', { name: spanish ? 'Configurar más adelante' : 'Set up later' }).click();
    await expect(page.locator('.setup-source-card strong')).toHaveText(['Demo Data', 'PurpleAir', 'OpenAQ', 'AirGradient']);
    const toggle = page.getByRole('checkbox', { name: spanish ? 'Habilitar Demo Data' : 'Enable Demo Data' });
    await expect(toggle).toBeChecked();
    if (!demoEnabled) {
      await toggle.click();
      await expect(toggle).not.toBeChecked();
    }
    const prefix = `../artifacts/demo-first-run/${language}-${width}-${demoEnabled ? 'enabled' : 'disabled'}`;
    await page.locator('.setup-wizard-overlay').evaluate(el => el.scrollTo(0, 0));
    await expect(page.locator('.setup-wizard-header')).toBeInViewport();
    await page.screenshot({ path: `${prefix}-wizard.png`, fullPage: true });
    expect(await page.locator('.setup-wizard-overlay').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await page.locator('.setup-wizard-overlay').evaluate(el => el.scrollTo(0, el.scrollHeight));
    await page.screenshot({ path: `${prefix}-wizard-actions.png`, fullPage: true });
    await page.getByRole('button', { name: spanish ? 'Guardar fuentes y continuar' : 'Save Sources & Continue' }).click();
    await page.getByRole('button', { name: spanish ? 'Saltar por ahora →' : 'Skip for Now →' }).click();
    const completion = page.waitForResponse(response => response.url().endsWith('/setup/complete'));
    await page.getByRole('button', { name: spanish ? 'Complete la configuración y comience a usar la plataforma' : 'Complete Setup & Start Using Platform' }).click();
    expect((await completion).status()).toBe(200);
    // No polling for seed availability: the first response after completion
    // must already contain the synthetic station and current observations.
    const devices = await (await page.request.get('/api/devices')).json();
    expect(devices).toHaveLength(demoEnabled ? 1 : 0);
    const measurements = await (await page.request.get('/api/measurements/pm25/latest')).json();
    expect(measurements).toHaveLength(demoEnabled ? 1 : 0);
    const state = JSON.parse(python(`
import json
from db import SessionLocal
from sqlalchemy import select, func
import models
with SessionLocal() as session:
    print(json.dumps({
        'measurements': session.scalar(select(func.count()).select_from(models.Measurement)),
        'jobs': session.scalar(select(func.count()).select_from(models.JobRun)),
    }))
`));
    expect(state).toEqual({ measurements: demoEnabled ? 54 : 0, jobs: 0 });
    if (demoEnabled) {
      expect(devices[0].latitude).toBe(52.0907);
      expect(devices[0].longitude).toBe(5.1214);
      expect(devices[0].name).toBe('DEMO — CompassAQ Sample Station');
      expect(Date.now() - Date.parse(measurements[0].observed_at)).toBeLessThan(300_000);
      expect(measurements[0].device.data_attribution.acquisition_path).toBe('demo_fixture');
    }
    await page.goto('/map');
    await expect(page.locator('.maplibregl-canvas')).toBeVisible();
    if (demoEnabled) await expect(page.locator('.maplibregl-marker')).toHaveCount(1);
    else await expect(page.locator('.maplibregl-marker')).toHaveCount(0);
    // Allow camera animation and basemap tiles to finish, never data generation.
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${prefix}-map.png`, fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (demoEnabled) {
      await page.locator('.maplibregl-marker').click();
      await expect(page.getByText('Demonstration Site — Not a real monitoring location', { exact: true }).first()).toBeVisible();
      await page.screenshot({ path: `${prefix}-detail.png`, fullPage: true });
    }
  });
}
