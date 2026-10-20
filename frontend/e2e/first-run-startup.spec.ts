import { expect, test, type Page } from '@playwright/test';


const screenshotDirectory = '../artifacts/startup-first-run';


async function mockFirstRunApi(
  page: Page,
  options: {
    readinessFailures?: number;
    alwaysNotReady?: boolean;
    holdNotReadyUntilReleased?: boolean;
    hasUsers?: boolean;
    defaultLanguageCode?: 'en' | 'es';
  } = {},
) {
  let readinessCalls = 0;
  let readinessReleased = false;
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/api/health/readiness') {
      readinessCalls += 1;
      const isReady = !options.alwaysNotReady
        && (!options.holdNotReadyUntilReleased || readinessReleased)
        && readinessCalls > (options.readinessFailures ?? 0);
      await route.fulfill({
        status: isReady ? 200 : 503,
        contentType: 'application/json',
        body: JSON.stringify({ status: isReady ? 'ready' : 'not_ready' }),
      });
      return;
    }
    if (pathname === '/api/setup/status') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          is_setup_required: true,
          has_users: options.hasUsers ?? false,
          default_language_code: options.defaultLanguageCode ?? 'en',
        }),
      });
      return;
    }
    if (pathname === '/api/setup/data-sources') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data_sources: [] }),
      });
      return;
    }
    await route.fulfill({ status: 404, body: '{}' });
  });
  return {
    releaseReadiness() {
      readinessReleased = true;
    },
  };
}


async function expectNoHorizontalScroll(page: Page) {
  expect(await page.evaluate(() => (
    document.documentElement.scrollWidth <= document.documentElement.clientWidth
  ))).toBe(true);
}


test('startup recovers into Welcome and Continue advances to administrator creation', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const startupApi = await mockFirstRunApi(page, { holdNotReadyUntilReleased: true });

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'CompassAQ is starting' })).toBeVisible();
  await page.screenshot({
    path: `${screenshotDirectory}/starting-en-desktop-1440x1000.png`,
    fullPage: true,
  });
  startupApi.releaseReadiness();

  await expect(page.getByRole('heading', { name: 'Welcome to CompassAQ' })).toBeVisible();
  await expect(page.getByText('Anything you skip can be configured later from Administration.')).toBeVisible();
  const continueButton = page.getByRole('button', { name: 'Continue' });
  await continueButton.focus();
  await expect(continueButton).toBeFocused();
  await expectNoHorizontalScroll(page);
  await page.waitForTimeout(400);
  await page.screenshot({
    path: `${screenshotDirectory}/welcome-en-desktop-1440x1000.png`,
    fullPage: true,
  });

  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page.getByRole('heading', { name: 'Create Admin Account' })).toBeVisible();
});


test('Spanish Welcome remains readable at a narrow mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockFirstRunApi(page, { defaultLanguageCode: 'es' });

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Bienvenido a CompassAQ' })).toBeVisible();
  await expect(page.getByText(/Todo lo que omita podrá configurarse más adelante/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Continuar' })).toBeVisible();
  await expectNoHorizontalScroll(page);
  await page.evaluate(() => document.querySelector('.setup-wizard-overlay')?.scrollTo(0, 0));
  await page.waitForTimeout(400);
  await page.locator('.setup-wizard-container').screenshot({
    path: `${screenshotDirectory}/welcome-es-mobile-390x844.png`,
  });
});


test('interrupted setup resumes at data sources on a tablet viewport', async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 1180 });
  await mockFirstRunApi(page, { hasUsers: true, defaultLanguageCode: 'es' });

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Configurar fuente de datos' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Bienvenido a CompassAQ' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '← Volver' })).toHaveCount(0);
  await expectNoHorizontalScroll(page);
  await page.waitForTimeout(400);
  await page.screenshot({
    path: `${screenshotDirectory}/resume-es-tablet-820x1180.png`,
    fullPage: true,
  });
});


test('persistent startup failure provides a keyboard-accessible Retry action', async ({ page }) => {
  await page.clock.install();
  await page.setViewportSize({ width: 390, height: 844 });
  await mockFirstRunApi(page, { alwaysNotReady: true });

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'CompassAQ is starting' })).toBeVisible();
  await page.clock.runFor(22_000);
  await expect(page.getByRole('heading', { name: 'CompassAQ could not finish starting' })).toBeVisible();
  const retryButton = page.getByRole('button', { name: 'Retry' });
  await retryButton.focus();
  await expect(retryButton).toBeFocused();
  await expectNoHorizontalScroll(page);
  await page.screenshot({
    path: `${screenshotDirectory}/startup-failure-en-mobile-390x844.png`,
    fullPage: true,
  });
});
