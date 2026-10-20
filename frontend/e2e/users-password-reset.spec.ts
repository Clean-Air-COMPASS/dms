import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const directory = '../artifacts/users-redesign/after';
const userId = '11111111-1111-4111-8111-111111111111';
const staff = { first_name: null as string | null, last_name: null as string | null, display_name: undefined as string | undefined, user_id: userId, org_id: userId, email: 'sofia.martinez@example.org', is_active: true, roles: ['analyst'], created_at: '2026-08-15T12:00:00Z', updated_at: '2026-09-05T09:30:00Z', failed_login_count: 0, locked_until: null as string | null, last_failed_login_at: null as string | null };

test('same-origin Docker proxy needs no application URL override', async ({ page }) => {
  const origin = process.env.USERS_ORIGIN_E2E_BASE_URL;
  test.skip(!origin, 'Start the disposable API without an application URL and a same-origin Nginx proxy');
  await mockUsers(page);
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.startsWith('/api/auth/') || path.startsWith('/api/admin/users')) {
      // Actual browser request through Nginx: do not synthesize Origin or Host.
      await route.continue();
    } else await route.fallback();
  });
  await page.goto(`${origin}/login`);
  await page.locator('input[type=email]').fill('browser-admin@example.org');
  await page.locator('input[type=password]').fill('BrowserOriginalCredential123!');
  await page.getByRole('button', { name: /^Sign in$/i }).click();
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto(`${origin}/admin/users`);
  await page.getByRole('link', { name: /View.*browser-staff/i }).click();
  const creationRequest = page.waitForRequest((request) => request.url().endsWith('/password-reset-link'));
  await page.getByRole('button', { name: 'Create password reset link' }).click();
  const issuedRequest = await creationRequest;
  const url = await page.getByRole('textbox', { name: 'Password reset URL' }).inputValue();
  expect(new URL(url).origin).toBe(origin);
  const poisoned = await page.request.post(issuedRequest.url(), { headers: {
    authorization: issuedRequest.headers().authorization, origin: origin!, host: 'evil.example',
    'x-forwarded-host': 'evil.example', 'x-forwarded-proto': 'https',
  } });
  expect(poisoned.status()).toBe(400);
  expect((await poisoned.json()).detail).toBe('reset_origin_invalid');
  // Rejected poisoning must leave the legitimately issued token usable.
  await page.goto(url);
  await expect(page.getByLabel('New password', { exact: true })).toBeVisible();
});

async function mockUsers(page: Page, language = 'en') {
  const state = { ready: false, sent: 0, links: 0, reset: 'valid', password: '', user: { ...staff }, authenticated: true, deleted: false };
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let body: unknown = {}; let status = 200;
    if (path === '/api/health/readiness') body = { status: 'ready' };
    else if (path === '/api/setup/status') body = { is_setup_required: false, has_users: true, default_language_code: language };
    else if (['/api/parameters', '/api/measurement-aggregation-capabilities', '/api/data-sources', '/api/air-quality-index/standards'].includes(path)) body = [];
    else if (path === '/api/auth/refresh') { body = { access_token: 'test-session' }; if (!state.authenticated) status = 401; }
    else if (path === '/api/auth/me') body = { ...staff, email: 'administrator@example.org', roles: ['admin'], scopes: ['users:write'], preferred_language_code: language, system_default_language_code: language };
    else if (path === '/api/admin/users/password-reset/readiness') body = { email_delivery_ready: state.ready };
    else if (path === '/api/admin/users/roles') body = [{ role_id: '1', name: 'admin' }, { role_id: '2', name: 'analyst' }, { role_id: '3', name: 'viewer' }];
    else if (path === '/api/admin/users') {
      if (request.method() === 'POST') { state.user = { ...state.user, ...request.postDataJSON() }; body = state.user; }
      else body = [...(state.deleted ? [] : [state.user]), { ...staff, user_id: 'disabled', email: 'james.chen@example.org', is_active: false, roles: ['viewer'] }];
    } else if (path.endsWith('/password-reset-link')) { state.links++; body = { reset_url: `${new URL(page.url()).origin}/reset-password#token=deterministic-test-link-${state.links}`, expires_at: '2026-09-05T13:00:00Z', expires_in_minutes: 60 }; }
    else if (path.endsWith('/password-reset-email')) { state.sent++; body = { success: true }; }
    else if (path === '/api/auth/password-reset/verify') { body = { valid: true, password_min_length: 12 }; if (state.reset !== 'valid') { status = 400; body = { detail: state.reset }; } }
    else if (path === '/api/auth/password-reset/complete') { state.password = request.postDataJSON().password; body = { success: true }; }
    else if (path === '/api/auth/login') { expect(request.postDataJSON().password).toBe(state.password); state.authenticated = true; body = { access_token: 'new-password-session' }; }
    else if (path === `/api/admin/users/${userId}`) {
      if (request.method() === 'DELETE') state.deleted = true;
      if (request.method() === 'PUT') {
        state.user = { ...state.user, ...request.postDataJSON() };
        state.user.first_name = state.user.first_name?.trim() || null;
        state.user.last_name = state.user.last_name?.trim() || null;
        state.user.display_name = [state.user.first_name, state.user.last_name].filter(Boolean).join(' ') || state.user.email;
      }
      body = state.user;
    } else if (path.endsWith('/unlock')) { state.user.failed_login_count = 0; state.user.locked_until = null; body = state.user; }
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  });
  return state;
}

async function capture(page: Page, name: string) {
  mkdirSync(directory, { recursive: true });
  await page.screenshot({ path: `${directory}/${name}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
}

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`user detail task priority ${language} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const state = await mockUsers(page, language);
    const selectors = ['.users-profile', '.users-access', '.users-roles', '.users-recovery', '.users-destructive'];
    for (const scenario of ['admin', 'non-admin', 'disabled', 'recovery-ready']) {
      state.user.roles = scenario === 'admin' ? ['admin'] : ['analyst'];
      state.user.is_active = scenario !== 'disabled';
      state.ready = scenario === 'recovery-ready';
      await page.goto(`/admin/users/${userId}`);
      await expect(page.locator('.users-roles input').first()).toBeVisible();
      await expect(page.locator('.users-profile h2')).toHaveText(language === 'es' ? 'Perfil' : 'Profile');
      await expect(page.locator('.users-recovery button').last()).toBeEnabled({ enabled: state.ready });
      if (state.ready) await expect(page.locator('.users-email-notice')).toHaveCount(0);
      else await expect(page.locator('.users-email-notice > span')).toHaveText(language === 'es' ? 'Envío de correo no disponible' : 'Email delivery unavailable');
      const sections = page.locator(selectors.join(', '));
      expect(await sections.evaluateAll(elements => elements.map(element => element.classList[1] ?? element.classList[0])))
        .toEqual(['users-profile', 'users-access', 'users-roles', 'users-recovery', 'users-destructive']);
      const bounds = await Promise.all(selectors.map(selector => page.locator(selector).boundingBox()));
      expect(bounds.every(Boolean)).toBeTruthy();
      if (width === 390) {
        for (let index = 1; index < bounds.length; index++) {
          expect(bounds[index]!.y).toBeGreaterThanOrEqual(bounds[index - 1]!.y + bounds[index - 1]!.height);
        }
      } else {
        expect(bounds[2]!.x).toBeGreaterThan(bounds[0]!.x + bounds[0]!.width);
        expect(bounds[2]!.y).toBe(bounds[0]!.y);
        expect(bounds[3]!.y).toBeGreaterThanOrEqual(Math.max(bounds[1]!.y + bounds[1]!.height, bounds[2]!.y + bounds[2]!.height));
      }
      for (const target of await page.locator('.user-detail-page button, .users-profile input, .role-checkbox, .users-metadata summary, .users-email-notice a').all()) {
        const box = await target.boundingBox();
        expect(box!.height).toBeGreaterThanOrEqual(44);
        expect(box!.width).toBeGreaterThanOrEqual(44);
      }
      await capture(page, `task-order-${scenario}-${language}-${width}`);
    }
    // Native tab order must follow routine access and roles before recovery.
    await page.locator('.users-access button').focus();
    await page.keyboard.press('Tab');
    await expect(page.locator('.users-roles input').first()).toBeFocused();
    await page.locator('.users-roles input').last().focus();
    await page.keyboard.press('Tab');
    await expect(page.locator('.users-metadata summary')).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.locator('.users-recovery button').first()).toBeFocused();
    const remove = page.locator('.users-destructive button');
    await remove.click();
    expect(state.deleted).toBe(false);
    await page.keyboard.press('Escape');
    await expect(remove).toBeFocused();
    expect(state.deleted).toBe(false);
  });
}

for (const language of ['en', 'es']) for (const width of [1440, 1280, 390]) {
  test(`profile and native checkbox acceptance ${language} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ colorScheme: 'dark' });
    const state = await mockUsers(page, language);
    state.user.roles = ['admin'];
    state.user.first_name = 'Sofía';
    state.user.last_name = 'Martínez';
    state.user.display_name = 'Sofía Martínez';
    await page.goto(`/admin/users/${userId}`);
    const spanish = language === 'es';
    const profile = page.locator('.users-profile');
    const first = profile.locator('input').nth(0);
    const last = profile.locator('input').nth(1);
    await expect(first).toHaveValue('Sofía');
    await expect(last).toHaveValue('Martínez');
    await expect(page.locator('.users-section-nav')).toHaveCount(0);
    const roles = page.locator('.role-checkbox input');
    await expect(roles.nth(0)).toBeChecked();
    await expect(roles.nth(1)).not.toBeChecked();
    await expect(roles.nth(2)).not.toBeChecked();
    for (const box of await roles.all()) {
      await expect(box).toHaveCSS('color-scheme', 'light');
      await expect(box).toHaveCSS('accent-color', 'rgb(6, 71, 137)');
    }
    await capture(page, `profile-${language}-${width}`);
    await page.keyboard.press('Tab');
    await roles.nth(1).focus();
    await expect(roles.nth(1)).toHaveCSS('outline-style', 'solid');
    await page.locator('.users-roles').screenshot({ path: `${directory}/checkbox-focus-${language}-${width}.png` });
    await page.keyboard.press('Space');
    await expect(roles.nth(1)).toBeChecked();
    await page.locator('.role-checkbox').nth(1).locator('strong').click();
    await expect(roles.nth(1)).not.toBeChecked();
    await first.fill('María');
    let release!: () => void;
    const pending = new Promise<void>(resolve => { release = resolve; });
    await page.route(`**/api/admin/users/${userId}`, async route => {
      if (route.request().method() === 'PUT') await pending;
      await route.fallback();
    });
    const save = profile.getByRole('button');
    await save.click();
    await expect(save).toBeDisabled();
    await expect(first).toBeDisabled();
    await expect(roles.nth(0)).toBeDisabled();
    await expect(roles.nth(1)).toBeDisabled();
    await capture(page, `profile-saving-${language}-${width}`);
    release();
    await expect(page.getByRole('heading', { name: 'María Martínez' })).toBeVisible();
    await expect(profile.getByRole('status')).toBeVisible();
    await capture(page, `profile-saved-${language}-${width}`);
    await page.goto('/admin/users');
    await expect(page.getByText('María Martínez', { exact: true })).toBeVisible();
    await capture(page, `profile-list-${language}-${width}`);
    await page.goto(`/admin/users/${userId}`);
    await page.route(`**/api/admin/users/${userId}`, async route => {
      if (route.request().method() === 'PUT') await route.fulfill({ status: 503, json: {} });
      else await route.fallback();
    });
    await first.fill('Unsaved');
    await save.click();
    await expect(profile.getByRole('alert')).toBeVisible();
    await expect(first).toHaveValue('Unsaved');
    await capture(page, `profile-error-${language}-${width}`);
    await expect(page.getByRole('heading', { name: spanish ? 'Eliminar cuenta' : 'Delete account', exact: true })).toBeVisible();
  });
}

for (const [width, height] of [[1440, 1000], [820, 1180], [390, 844]]) {
  test(`Users visual and recovery workflow ${width}`, async ({ page, context }) => {
    await page.setViewportSize({ width, height });
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    const state = await mockUsers(page);
    await page.goto('/admin/users');
    await expect(page.getByRole('link', { name: /View.*sofia/i })).toBeVisible();
    await capture(page, `users-list-en-${width}`);
    if (width === 1440) {
      await page.getByRole('region', { name: 'Users', exact: true }).focus();
      await capture(page, 'users-list-keyboard-focus');
    }
    await page.getByRole('button', { name: 'New User', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Account Details' })).toBeVisible();
    await capture(page, `new-user-en-${width}`);
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.getByRole('link', { name: /View.*sofia/i }).click();
    await expect(page.getByRole('heading', { name: 'Password recovery' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send password reset email' })).toBeDisabled();
    await expect(page.getByText(/You can still create and copy/)).toBeVisible();
    await capture(page, `detail-unavailable-en-${width}`);
    await page.getByRole('button', { name: 'Disable User', exact: true }).click();
    await capture(page, `confirm-disable-en-${width}`);
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
    const create = page.getByRole('button', { name: 'Create password reset link' });
    await create.click();
    await expect(page.getByRole('dialog')).toBeVisible();
    const resetUrl = await page.getByRole('textbox', { name: 'Password reset URL' }).inputValue();
    await capture(page, `reset-link-modal-en-${width}`);
    await page.getByRole('button', { name: 'Done', exact: true }).focus();
    await page.keyboard.press('Tab');
    await expect(page.getByRole('textbox', { name: 'Password reset URL' })).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(page.getByRole('button', { name: 'Done', exact: true })).toBeFocused();
    await page.getByRole('button', { name: 'Copy link' }).click();
    await expect(page.getByText('Link copied.')).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(resetUrl);
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(create).toBeFocused();
    expect(await page.content()).not.toContain('deterministic-test-link');
    state.ready = true;
    await page.reload();
    await expect(page.getByRole('button', { name: 'Send password reset email' })).toBeEnabled();
    await capture(page, `detail-ready-en-${width}`);
    await page.getByRole('button', { name: 'Send password reset email' }).click();
    await expect(page.getByText(/Password reset email sent/)).toBeVisible();
    expect(state.sent).toBe(1);
    state.authenticated = false;
    await page.goto(resetUrl);
    await expect(page.getByLabel('New password', { exact: true })).toBeVisible();
    expect(new URL(page.url()).hash).toBe('');
    await capture(page, `reset-password-en-${width}`);
    await page.getByLabel('New password', { exact: true }).fill('ReplacementCredential123!');
    await page.getByLabel('Confirm password', { exact: true }).fill('ReplacementCredential123!');
    await page.getByRole('button', { name: 'Set new password' }).click();
    await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();
    await page.getByRole('link', { name: 'Go to sign in' }).click();
    await page.locator('input[type=email]').fill(staff.email);
    await page.locator('input[type=password]').fill('ReplacementCredential123!');
    await page.getByRole('button', { name: /^Sign in$/i }).click();
    await expect(page).not.toHaveURL(/\/login/);
    for (const code of ['reset_invalid', 'reset_expired']) {
      state.reset = code;
      await page.goto('/reset-password#token=invalid');
      await expect(page.getByRole('alert')).toBeVisible();
      await capture(page, `${code}-en-${width}`);
    }
  });
}

test('Spanish Users and reset views', async ({ page }) => {
  await mockUsers(page, 'es');
  for (const [width, height] of [[1440, 1000], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await page.goto('/admin/users');
    await expect(page.getByRole('heading', { name: 'Usuarios', exact: true })).toBeVisible();
    await capture(page, `users-list-es-${width}`);
    await page.goto('/admin/users/new');
    await expect(page.locator('input[type=email]')).toBeVisible();
    await capture(page, `new-user-es-${width}`);
    await page.goto(`/admin/users/${userId}`);
    await expect(page.getByRole('heading', { name: 'Recuperación de contraseña' })).toBeVisible();
    await capture(page, `detail-unavailable-es-${width}`);
    await page.getByRole('button', { name: 'Crear enlace para restablecer contraseña' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await capture(page, `reset-link-modal-es-${width}`);
    await page.goto('/reset-password#token=spanish-test');
    await expect(page.getByLabel('Nueva contraseña', { exact: true })).toBeVisible();
    await capture(page, `reset-password-es-${width}`);
  }
});

test('real PostgreSQL reset changes the password used by sign in', async ({ page }) => {
  const api = process.env.USERS_RESET_E2E_API;
  test.skip(!api, 'Start tests/password_reset_browser_server.py and set USERS_RESET_E2E_API');
  await mockUsers(page);
  // Forward security and user operations to the disposable real API. Startup
  // data unrelated to Users remains deterministic and needs no provider access.
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, '');
    if (path.startsWith('/auth/') || path.startsWith('/admin/users')) {
      const response = await route.fetch({ url: `${api}${path}` });
      await route.fulfill({ response });
    } else await route.fallback();
  });
  await page.goto('/login');
  await page.locator('input[type=email]').fill('browser-admin@example.org');
  await page.locator('input[type=password]').fill('BrowserOriginalCredential123!');
  await page.getByRole('button', { name: /^Sign in$/i }).click();
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto('/admin/users');
  await page.getByRole('button', { name: 'New User', exact: true }).click();
  const temporaryEmail = `temporary-${Date.now()}@example.org`;
  await page.getByLabel(/^Email/).fill(temporaryEmail);
  await page.getByLabel(/^Password/).fill('BrowserCreationCredential123!');
  await page.getByLabel(/^Confirm Password/).fill('BrowserCreationCredential123!');
  await page.getByRole('checkbox', { name: /^Analyst\b/ }).check();
  await page.getByRole('button', { name: 'Create User', exact: true }).click();
  await expect(page.getByRole('heading', { name: temporaryEmail })).toBeVisible();
  await page.getByRole('checkbox', { name: /^Administrator\b/ }).check();
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  await page.getByRole('button', { name: 'Disable User', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Disable', exact: true }).click();
  await page.getByRole('button', { name: 'Enable User', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Enable', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Disable User', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Delete User', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Delete User', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Users', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: `View ${temporaryEmail}` })).toHaveCount(0);
  await page.getByRole('link', { name: /View.*browser-staff/i }).click();
  await page.getByRole('button', { name: 'Create password reset link' }).click();
  const url = await page.getByRole('textbox', { name: 'Password reset URL' }).inputValue();
  await page.getByRole('button', { name: 'Done' }).click();
  await page.context().clearCookies();
  await page.goto(url);
  await page.getByLabel('New password', { exact: true }).fill('BrowserReplacementCredential456!');
  await page.getByLabel('Confirm password', { exact: true }).fill('BrowserReplacementCredential456!');
  await page.getByRole('button', { name: 'Set new password' }).click();
  await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();
  await page.getByRole('link', { name: 'Go to sign in' }).click();
  await page.locator('input[type=email]').fill('browser-staff@example.org');
  await page.locator('input[type=password]').fill('BrowserReplacementCredential456!');
  await page.getByRole('button', { name: /^Sign in$/i }).click();
  await expect(page).not.toHaveURL(/\/login/);
});


test('account workspace preserves filters, creation, roles, status, unlock and delete', async ({ page }) => {
  const state = await mockUsers(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/admin/users');
  await expect(page.getByRole('link', { name: /View.*sofia/ })).toBeVisible();
  await page.getByRole('combobox', { name: 'Status', exact: true }).selectOption('disabled');
  await expect(page.getByRole('link', { name: /View.*sofia/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'Reset', exact: true }).click();
  await page.getByRole('combobox', { name: 'Role', exact: true }).selectOption('viewer');
  await expect(page.getByRole('link', { name: /View.*james/ })).toBeVisible();
  await expect(page.getByRole('link', { name: /View.*sofia/ })).toHaveCount(0);
  await page.getByLabel('Email', { exact: true }).fill('missing');
  await expect(page.getByText('No users found.')).toBeVisible();
  await capture(page, 'users-list-empty');
  await page.getByRole('button', { name: 'New User', exact: true }).click();
  await page.getByLabel(/^Email/).fill('new.staff@example.org');
  await page.getByLabel(/^Password/).fill('BrowserCreationCredential123!');
  await page.getByLabel(/^Confirm Password/).fill('BrowserCreationCredential123!');
  await page.getByRole('checkbox', { name: /^Analyst/ }).check();
  await capture(page, 'new-user-filled');
  await page.getByRole('button', { name: 'Create User', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'new.staff@example.org' })).toBeVisible();
  await page.getByRole('checkbox', { name: /^Viewer/ }).check();
  await expect(page.getByText('Unsaved changes')).toBeVisible();
  await capture(page, 'detail-unsaved-roles');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  expect(state.user.roles).toEqual(['analyst', 'viewer']);
  await page.getByRole('button', { name: 'Disable User', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Disable', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Enable User', exact: true })).toBeVisible();
  expect(state.user.is_active).toBe(false);
  await page.getByRole('button', { name: 'Enable User', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Enable', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Disable User', exact: true })).toBeVisible();
  state.user.failed_login_count = 5;
  state.user.locked_until = '2099-09-05T12:00:00Z';
  state.user.last_failed_login_at = '2026-09-05T09:30:00Z';
  await page.reload();
  await expect(page.getByRole('button', { name: 'Unlock Account', exact: true })).toBeVisible();
  for (const [width, height] of [[1440, 1000], [820, 1180], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await capture(page, `detail-locked-en-${width}`);
  }
  await page.getByRole('button', { name: 'Unlock Account', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Unlock Account', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Unlock Account', exact: true })).toHaveCount(0);
  expect(state.user.failed_login_count).toBe(0);
  await page.getByRole('button', { name: 'Delete User', exact: true }).click();
  await capture(page, 'confirm-delete-mobile');
  await page.getByRole('dialog').getByRole('button', { name: 'Delete User', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Users', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: /View.*new.staff/ })).toHaveCount(0);
  expect(state.deleted).toBe(true);
});


test('Users loading, errors, long identities and document structure remain usable', async ({ page }) => {
  const state = await mockUsers(page);
  await page.setViewportSize({ width: 390, height: 844 });
  let release: () => void = () => {};
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/admin/users', async route => {
    await pending;
    await route.fulfill({ status: 503, json: { detail: 'unavailable' } });
  });
  await page.goto('/admin/users');
  await expect(page.getByRole('status')).toContainText('Loading users');
  await expect(page.getByRole('table')).toHaveCount(0);
  await capture(page, 'users-list-loading-mobile');
  release();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('table')).toHaveCount(0);
  await capture(page, 'users-list-error-mobile');
  state.user.email = 'long.account.management.identity@regional-air-quality.example.org';
  await page.goto(`/admin/users/${userId}`);
  await expect(page.getByRole('heading', { name: state.user.email })).toBeVisible();
  await capture(page, 'detail-long-identity-mobile');
  await expect(page.getByRole('navigation', { name: 'Account management' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Roles', exact: true })).toBeVisible();
  await page.locator('.users-metadata summary').click();
  await expect(page.getByText(userId, { exact: true })).toBeVisible();
  await capture(page, 'detail-metadata-mobile');
});
