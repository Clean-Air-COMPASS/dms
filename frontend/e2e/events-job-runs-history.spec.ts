import { expect, test, type Page } from '@playwright/test';

type Language = 'en' | 'es';

const user = {
  user_id: 'history-review-user',
  first_name: 'History',
  last_name: 'Reviewer',
  display_name: 'History Reviewer',
  passkey_count: 0,
  email: 'history@example.org',
  org_id: 'history-review-org',
  roles: ['admin'],
  scopes: ['users:write'],
};

async function mockHistory(page: Page, language: Language) {
  const requests: URL[] = [];
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api/, '');
    let body: unknown = [];
    if (path === '/health/readiness') body = { status: 'ready' };
    else if (path === '/setup/status') body = { is_setup_required: false, has_users: true, default_language_code: language };
    else if (path === '/auth/refresh') body = { access_token: 'history-review-session' };
    else if (path === '/auth/me') body = { ...user, preferred_language_code: language, system_default_language_code: language };
    else if (path === '/parameters' || path === '/measurement-aggregation-capabilities' || path === '/data-sources') body = [];
    else if (path === '/air-quality-index/standards') body = [];
    else if (path === '/version') body = { version: 'history-review' };
    else if (path === '/admin/jobs/runs' || path === '/admin/events') {
      requests.push(url);
      const jobs = path.endsWith('/jobs/runs');
      const offset = Number(url.searchParams.get('offset') || 0);
      const item = jobs
        ? { job_run_id: 126 - offset, job_schedule_id: 1, task: 'openaq_import', status: 'success', started_at: '2026-09-20T14:00:00Z', finished_at: '2026-09-20T14:01:00Z', summary: { devices_processed: 2, measurements_inserted: 12 }, error_message: null }
        : { event_id: 126 - offset, event_type: 'auth.login.failed', source: 'auth', severity: 'warning', created_at: '2026-09-20T14:00:00Z', message: 'A sign-in attempt failed.', actor_display_name: 'Example administrator' };
      body = {
        items: [item],
        total: 126,
        options: jobs
          ? { task: ['openaq_import', 'purpleair_import'], status: ['success', 'failed'] }
          : { event_type: ['auth.login.failed'], source: ['auth'], severity: ['warning', 'error'] },
      };
    }
    await route.fulfill({ status: 200, json: body });
  });
  return requests;
}

for (const [language, width] of [['en', 1440], ['es', 390]] as const) {
  test(`history paging, filters, readable codes, dates, and tabs work in ${language}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(initialLanguage => {
      localStorage.setItem('compassaq.language', initialLanguage);
    }, language === 'en' ? 'es' : 'en');
    const requests = await mockHistory(page, language);
    await page.goto('/admin/events');

    const labels = language === 'en'
      ? { range: 'Showing 1–25 of 126 matching records', task: 'OpenAQ import', next: 'Next', previous: 'Previous', eventTab: 'System events', event: 'Sign-in failed', code: 'Technical code', from: 'From date (UTC)', to: 'Through date (UTC)', apply: 'Apply dates' }
      : { range: 'Mostrando 1–25 de 126 registros coincidentes', task: 'Importación de OpenAQ', next: 'Siguiente', previous: 'Anterior', eventTab: 'Eventos del sistema', event: 'Falló el inicio de sesión', code: 'Código técnico', from: 'Desde la fecha (UTC)', to: 'Hasta la fecha (UTC)', apply: 'Aplicar fechas' };

    await expect(page.getByText(labels.range)).toBeVisible();
    await expect(page.getByRole('cell', { name: labels.task })).toBeVisible();
    await page.locator('.history-code summary').first().click();
    await expect(page.getByText('openaq_import')).toBeVisible();

    await page.getByRole('button', { name: labels.next, exact: true }).click();
    await expect.poll(() => requests.at(-1)?.searchParams.get('offset')).toBe('25');
    await page.getByRole('button', { name: labels.previous, exact: true }).click();
    await expect.poll(() => requests.at(-1)?.searchParams.get('offset')).toBe('0');

    const taskFilter = page.getByLabel(language === 'en' ? 'Task:' : 'Tarea:');
    await taskFilter.selectOption('purpleair_import');
    await expect.poll(() => requests.at(-1)?.searchParams.get('task')).toBe('purpleair_import');

    const jobsTab = page.getByRole('tab', { name: language === 'en' ? 'Job Runs' : 'Ejecuciones de trabajos' });
    await jobsTab.focus();
    await page.keyboard.press('ArrowRight');
    const eventsTab = page.getByRole('tab', { name: labels.eventTab });
    await expect(eventsTab).toBeFocused();
    await expect(eventsTab).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('cell', { name: labels.event })).toBeVisible();
    await page.locator('.history-code summary').click();
    await expect(page.getByText('auth.login.failed')).toBeVisible();

    await page.getByLabel(labels.from).fill('2026-09-01');
    await page.getByLabel(labels.to).fill('2026-09-20');
    await page.getByRole('button', { name: labels.apply }).click();
    await expect.poll(() => requests.at(-1)?.searchParams.get('started_after')).toBe('2026-09-01T00:00:00Z');
    await expect.poll(() => requests.at(-1)?.searchParams.get('started_before')).toBe('2026-09-21T00:00:00.000Z');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
