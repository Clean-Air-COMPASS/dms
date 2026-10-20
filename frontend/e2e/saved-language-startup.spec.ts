import { expect, test, type Page } from '@playwright/test';

type Language = 'en' | 'es';

const user = {
  user_id: 'language-review-user',
  first_name: 'Language',
  last_name: 'Reviewer',
  display_name: 'Language Reviewer',
  passkey_count: 0,
  email: 'language@example.org',
  org_id: 'language-review-org',
  roles: ['admin'],
  scopes: ['users:write'],
};

const emailConfiguration = {
  enabled: false,
  status: 'not_configured',
  status_reason_codes: ['email_not_configured'],
  smtp_host: null,
  smtp_port: null,
  smtp_security_mode: null,
  smtp_username: null,
  password_configured: false,
  from_email: null,
  from_display_name: null,
  reply_to_email: null,
  administrator_recipients: [],
  last_test_status: null,
  last_test_error_code: null,
  last_tested_at: null,
  created_at: null,
  updated_at: null,
};

const summaryConfiguration = {
  enabled: false,
  cadence: 'daily',
  daily_send_time: '07:00:00',
  reporting_timezone: 'UTC',
  reporting_timezone_source: 'system_preferences',
  reporting_timezone_override: null,
  system_timezone: 'UTC',
  effective_at: null,
  schedule_status: 'summary_off',
  blocker_codes: [],
  email_delivery_ready: false,
  next_due_at: null,
  next_reporting_window: null,
  last_scheduled_delivery: null,
};

const copy = {
  en: { admin: 'Admin', devices: 'Devices', email: 'Email & notifications', login: 'Sign in' },
  es: { admin: 'Administración', devices: 'Dispositivos', email: 'Correo y notificaciones', login: 'Iniciar sesión' },
} satisfies Record<Language, Record<string, string>>;

async function mockStartupApis(
  page: Page,
  options: { accountLanguage?: Language | null; setupLanguage?: Language; signedIn?: boolean } = {},
) {
  const state = {
    signedIn: options.signedIn ?? true,
    setupLanguage: options.setupLanguage ?? 'en',
    user: { ...user, preferred_language_code: options.accountLanguage ?? 'en', system_default_language_code: 'en' as Language },
  };

  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api/, '');
    const data = request.postData() ? request.postDataJSON() : {};
    let body: unknown = [];
    let status = 200;

    if (path === '/health/readiness') body = { status: 'ready' };
    else if (path === '/setup/status') body = { is_setup_required: false, has_users: true, default_language_code: state.setupLanguage };
    else if (path === '/auth/refresh') {
      body = state.signedIn ? { access_token: 'language-review-session' } : {};
      if (!state.signedIn) status = 401;
    } else if (path === '/auth/me') {
      body = state.user;
      if (!state.signedIn) status = 401;
    } else if (path === '/auth/me/preferences') {
      state.user.preferred_language_code = data.preferred_language_code;
      body = state.user;
    } else if (path === '/parameters' || path === '/measurement-aggregation-capabilities' || path === '/data-sources') body = [];
    else if (path === '/air-quality-index/standards') body = [];
    else if (path === '/version') body = { version: 'language-review' };
    else if (path === '/admin/devices' || path === '/admin/external_apis') body = [];
    else if (path === '/admin/email/configuration') body = emailConfiguration;
    else if (path === '/admin/email/administrator-summary') body = summaryConfiguration;

    await route.fulfill({ status, json: body });
  });

  return state;
}

async function useLocalLanguage(page: Page, language: Language): Promise<void> {
  await page.addInitScript((initialLanguage) => {
    window.localStorage.setItem('compassaq.language', initialLanguage);
  }, language);
}

async function expectLanguage(page: Page, language: Language): Promise<void> {
  await expect.poll(() => page.evaluate(() => document.documentElement.lang)).toBe(language);
  await expect(page.locator('#user-menu-dropdown')).toHaveCount(0);
  await page.locator('.user-menu__trigger').click();
  await expect(page.locator('#account-language-selector')).toHaveValue(language);
  await page.keyboard.press('Escape');
}

for (const [width, height] of [[1440, 1000], [390, 844]] as const) {
  for (const language of ['en', 'es'] as const) {
    test(`authenticated ${language} language survives startup, refresh, and Admin deep links at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height });
      await useLocalLanguage(page, language === 'es' ? 'en' : 'es');
      await mockStartupApis(page, { accountLanguage: language, setupLanguage: 'en' });

      await page.goto('/admin');
      await expect(page.getByRole('heading', { name: copy[language].admin, exact: true })).toBeVisible();
      await expectLanguage(page, language);
      expect(await page.evaluate(() => window.localStorage.getItem('compassaq.language'))).toBe(language);

      await page.reload();
      await expect(page.getByRole('heading', { name: copy[language].admin, exact: true })).toBeVisible();
      await expectLanguage(page, language);

      await page.goto('/admin/devices');
      await expect(page.getByRole('heading', { name: copy[language].devices, exact: true })).toBeVisible();
      await expectLanguage(page, language);

      await page.goto('/admin/email');
      await expect(page.getByRole('heading', { name: copy[language].email, exact: true })).toBeVisible();
      await expectLanguage(page, language);

      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`authenticated-${language}-${width}.png`), fullPage: true });
    });
  }
}

for (const [width, height] of [[1440, 1000], [390, 844]] as const) {
  test(`account menu changes the live language at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height });
    await useLocalLanguage(page, 'en');
    const state = await mockStartupApis(page, { accountLanguage: 'en' });

    await page.goto('/admin');
    await expect(page.getByRole('heading', { name: copy.en.admin, exact: true })).toBeVisible();
    await page.locator('.user-menu__trigger').click();
    await page.screenshot({ path: testInfo.outputPath(`account-menu-en-${width}.png`), fullPage: true });
    await page.locator('#account-language-selector').selectOption('es');
    await expect(page.getByRole('heading', { name: copy.es.admin, exact: true })).toBeVisible();
    await expect(page.locator('#account-language-selector')).toHaveValue('es');
    await expect.poll(() => state.user.preferred_language_code).toBe('es');
    expect(await page.evaluate(() => window.localStorage.getItem('compassaq.language'))).toBe('es');

    await page.locator('#account-language-selector').selectOption('en');
    await expect(page.getByRole('heading', { name: copy.en.admin, exact: true })).toBeVisible();
    await expect(page.locator('#account-language-selector')).toHaveValue('en');
    await expect.poll(() => state.user.preferred_language_code).toBe('en');
  });
}

test('signed-out login keeps the anonymous local language fallback', async ({ page }) => {
  await useLocalLanguage(page, 'es');
  await mockStartupApis(page, { accountLanguage: null, setupLanguage: 'en', signedIn: false });

  await page.goto('/login');
  await expect(page.getByRole('heading', { name: copy.es.login, exact: true })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Idioma' })).toHaveValue('es');
  expect(await page.evaluate(() => document.documentElement.lang)).toBe('es');
});
