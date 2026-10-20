import { expect, test, type Page } from '@playwright/test';

const challenge = Buffer.from('account-browser-acceptance-challenge').toString('base64url');
const screenshots = '../artifacts/my-account';

async function mockAccount(page: Page, language: string) {
  const state = {
    user: { user_id: 'account-review-user', org_id: 'review-org', email: 'jennifer@example.com',
      first_name: 'Jennifer', last_name: 'DeWinter', display_name: 'Jennifer DeWinter',
      passkey_count: 0, roles: ['admin'], scopes: ['users:write'], preferred_language_code: language, system_default_language_code: language },
    keys: [] as { id: string; name: string | null; created_at: string | null; last_used_at: string | null }[],
    rejectProfile: false, rejectEmail: false, signedIn: true, proofCount: 0, session: 'review-session',
    registrationCount: 0, assertionCount: 0,
  };
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.slice(4);
    const method = request.method();
    const data = request.postData() ? request.postDataJSON() : {};
    let body: unknown = {}; let status = 200;
    if (path === '/health/readiness') body = { status: 'ready' };
    else if (path === '/setup/status') body = { is_setup_required: false, has_users: true, default_language_code: language };
    else if (['/parameters', '/measurement-aggregation-capabilities', '/data-sources', '/air-quality-index/standards', '/admin/job-runs'].includes(path)) body = [];
    else if (path === '/version') body = { version: 'account-review' };
    else if (path === '/auth/login') { state.signedIn = true; body = { access_token: state.session }; }
    else if (path === '/auth/refresh') { body = { access_token: state.session }; if (!state.signedIn) status = 401; }
    else if (path === '/auth/me') {
      if (method === 'PATCH') {
        if (state.rejectProfile) { status = 503; body = { detail: { message: 'SECRET backend diagnostic' } }; }
        else { state.user.first_name = data.first_name; state.user.last_name = data.last_name; state.user.display_name = [data.first_name, data.last_name].filter(Boolean).join(' ') || state.user.email; }
      }
      if (status === 200) body = state.user;
    } else if (path === '/auth/me/preferences') { state.user.preferred_language_code = data.preferred_language_code; body = state.user; }
    else if (path === '/auth/passkeys') body = { passkeys: state.keys };
    else if (path === '/auth/reauthenticate') { state.proofCount++; body = { reauthentication_token: 'review-proof' }; }
    else if (path === '/auth/passkeys/register/options') {
      expect(data.reauthentication_token).toBe('review-proof');
      body = { challenge, rp: { id: new URL(page.url()).hostname, name: 'CompassAQ' },
        user: { id: Buffer.from(state.user.user_id).toString('base64url'), name: state.user.email, displayName: state.user.display_name },
        pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
        authenticatorSelection: { residentKey: 'required', userVerification: 'required' }, attestation: 'none',
        excludeCredentials: state.keys.map((key) => ({ id: key.id, type: 'public-key' })) };
    } else if (path === '/auth/passkeys/register/verify') {
      expect(data.credential.response.attestationObject).toBeTruthy(); state.registrationCount++;
      state.keys.push({ id: data.credential.id, name: data.name || null, created_at: '2026-09-07T10:00:00Z', last_used_at: null });
      state.user.passkey_count = state.keys.length; body = { success: true };
    } else if (path === '/auth/passkeys/reauthenticate/options') {
      body = { challenge, rpId: new URL(page.url()).hostname, userVerification: 'required', allowCredentials: state.keys.map((key) => ({ id: key.id, type: 'public-key' })) };
    } else if (path === '/auth/passkeys/reauthenticate/verify') {
      expect(data.credential.response.signature).toBeTruthy(); state.assertionCount++; body = { reauthentication_token: 'review-proof' };
    } else if (method === 'DELETE' && path.startsWith('/auth/passkeys/')) {
      expect(request.headers()['x-reauthentication-token']).toBe('review-proof');
      state.keys = state.keys.filter((key) => !path.endsWith(key.id)); state.user.passkey_count = state.keys.length; body = { success: true };
    } else if (path === '/auth/me/email' || path === '/auth/me/password') {
      expect(data.reauthentication_token).toBe('review-proof');
      if (state.rejectEmail) { status = 409; body = { detail: { error_code: 'email_already_in_use' } }; }
      else { if (data.email) state.user.email = data.email; state.session = 'replacement-review-session'; body = { access_token: state.session }; }
    } else if (path === '/auth/logout') { state.signedIn = false; body = { success: true }; }
    else if (path === '/admin/system-preferences') body = { geoapify_api_key: '', default_language_code: language, system_timezone: 'America/Los_Angeles', updated_at: '2026-09-07T10:00:00Z', last_updated_by_display_name: 'Jennifer DeWinter', last_updated_by_email: 'jennifer@example.com' };
    else if (path === '/admin/events') body = [{ event_id: 1, event_type: 'profile_updated', source: 'auth', severity: 'info', message: 'Profile updated', created_at: '2026-09-07T10:00:00Z', actor_display_name: 'Jennifer DeWinter', actor_email: 'jennifer@example.com' }];
    else if (path.includes('job-runs')) body = [];
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  });
  return state;
}

async function capture(page: Page, name: string) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const dialog = page.getByRole('dialog');
  if (await dialog.count()) {
    const bounds = await dialog.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
    expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  }
  await page.screenshot({ path: `${screenshots}/${name}.png`, fullPage: true, animations: 'disabled' });
}

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`account visual states ${language} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const state = await mockAccount(page, language); const es = language === 'es'; const prefix = `${language}-${width}`;
    state.user.roles = []; state.user.scopes = [];
    await page.goto('/account');
    await expect(page.getByRole('heading', { name: es ? 'Mi cuenta' : 'My Account', exact: true })).toBeVisible();
    await expect(page.getByText(es ? 'Aún no tienes claves de acceso.' : 'You have no passkeys yet.')).toBeVisible();
    await capture(page, `${prefix}-profile-zero`);
    const firstName = page.getByLabel(es ? 'Nombre' : 'First name', { exact: true });
    await firstName.fill('María'); await page.getByRole('button', { name: es ? 'Guardar perfil' : 'Save profile' }).click();
    await expect(page.getByRole('status')).toHaveText(es ? 'Guardado' : 'Saved'); await capture(page, `${prefix}-saved`);
    state.rejectProfile = true; await firstName.fill('Changed'); await page.getByRole('button', { name: es ? 'Guardar perfil' : 'Save profile' }).click();
    await expect(page.getByRole('alert')).toBeVisible(); await capture(page, `${prefix}-save-error`); state.rejectProfile = false;
    await page.getByRole('button', { name: es ? 'Cambiar correo' : 'Change email', exact: true }).click();
    await expect(page.getByLabel(es ? 'Nuevo correo electrónico' : 'New email address')).toBeFocused();
    await capture(page, `${prefix}-reauthentication`);
    await page.keyboard.press('Escape'); await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByRole('button', { name: es ? 'Cambiar correo' : 'Change email', exact: true })).toBeFocused();
    state.keys = [{ id: 'one', name: 'Windows laptop', created_at: '2026-09-07T10:00:00Z', last_used_at: '2026-09-07T11:00:00Z' }]; state.user.passkey_count = 1;
    await page.reload(); await expect(page.getByText('Windows laptop')).toBeVisible(); await capture(page, `${prefix}-one-passkey`);
    state.keys.push({ id: 'two', name: null, created_at: null, last_used_at: null }, { id: 'three', name: 'Air quality laboratory — shared field monitoring laptop', created_at: null, last_used_at: null });
    state.user.first_name = ''; state.user.last_name = ''; state.user.display_name = state.user.email;
    await page.reload(); await expect(page.getByText(es ? 'Clave de acceso sin nombre' : 'Unnamed passkey')).toBeVisible();
    await capture(page, `${prefix}-multiple-no-names`);
    await page.locator('.account-passkey-list button').first().click(); await capture(page, `${prefix}-removal`); await page.keyboard.press('Escape');
    await page.getByRole('button', { name: /jennifer@example.com/ }).click();
    await expect(page.locator('#user-menu-dropdown')).toContainText(state.user.email); await capture(page, `${prefix}-menu-fallback`);
    await page.keyboard.press('Escape');
    state.user.display_name = 'Jennifer DeWinter'; await page.reload();
    await page.getByRole('button', { name: /Jennifer DeWinter/ }).click(); await capture(page, `${prefix}-menu-name`);
    await page.locator('#user-menu-dropdown').getByLabel(es ? 'Idioma' : 'Language').selectOption(es ? 'en' : 'es');
    await expect(page.getByRole('heading', { name: es ? 'My Account' : 'Mi cuenta', exact: true })).toBeVisible();
    await expect(page).toHaveTitle(es ? 'My Account' : 'Mi cuenta');
    await page.locator('#user-menu-dropdown').getByLabel(es ? 'Language' : 'Idioma').selectOption(language);
    await page.getByRole('link', { name: es ? 'Mi cuenta' : 'My Account', exact: true }).click();
    state.user.roles = ['admin']; state.user.scopes = ['users:write'];
    await page.goto('/admin/system-preferences'); await expect(page.getByText(/Jennifer DeWinter/)).toBeVisible(); await capture(page, `${prefix}-preferences-attribution`);
    await page.goto('/admin/events?tab=events'); await expect(page.getByText('jennifer@example.com', { exact: true })).toBeVisible(); await capture(page, `${prefix}-event-attribution`);
    await page.getByRole('button', { name: /Jennifer DeWinter/ }).click();
    await page.locator('#user-menu-dropdown').getByRole('button', { name: es ? 'Cerrar sesión' : 'Sign Out' }).click(); await expect(page).toHaveURL(/\/login/);
  });
}

test('browser passkey ceremonies, replacement sessions, and removal', async ({ page }) => {
  const state = await mockAccount(page, 'en');
  const cdp = await page.context().newCDPSession(page); await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', { options: { protocol: 'ctap2', transport: 'internal', hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } });
  // WebAuthn relying parties require a domain, even for a loopback review stack.
  const accountUrl = new URL('/account', test.info().project.use.baseURL ?? 'http://localhost');
  if (accountUrl.hostname === '127.0.0.1') accountUrl.hostname = 'localhost';
  await page.goto(accountUrl.href); await page.getByRole('button', { name: 'Add passkey', exact: true }).click();
  await page.getByLabel('Passkey name (optional)').fill('Virtual laptop'); await page.getByLabel('Current password').fill('ReviewPassword1!');
  await page.getByRole('button', { name: 'Verify and add passkey' }).click(); await expect(page.getByText('Passkey added.')).toBeVisible();
  expect(state.registrationCount).toBe(1);
  await page.getByRole('button', { name: 'Change email', exact: true }).click(); await page.getByLabel('New email address').fill('new@example.com');
  await page.getByLabel('Verify with passkey').check(); await page.getByRole('button', { name: 'Verify and change email' }).click();
  await expect(page.getByText('Email updated. You are still signed in.')).toBeVisible(); expect(state.assertionCount).toBe(1);
  await expect(page.getByText('new@example.com', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Change password', exact: true }).click();
  await page.getByLabel('New password', { exact: true }).fill('ChangedPassword1!'); await page.getByLabel('Confirm password').fill('ChangedPassword1!');
  await page.getByLabel('Current password').fill('ReviewPassword1!'); await capture(page, 'password-dialog');
  await page.getByRole('button', { name: 'Verify and change password' }).click(); await expect(page.getByText('Password updated. Your passkeys are unchanged.')).toBeVisible();
  await page.getByRole('button', { name: 'Remove “Virtual laptop”?' }).click(); await page.getByLabel('Verify with passkey').check();
  await page.getByRole('button', { name: 'Verify and remove passkey' }).click(); await expect(page.getByText('Passkey removed.')).toBeVisible(); expect(state.assertionCount).toBe(2);
});

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`Admin user menu follows login and current-user updates ${language} ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    const state = await mockAccount(page, language);
    page.setDefaultTimeout(15000);
    state.signedIn = false;
    const es = language === 'es';
    const adminName = es ? 'Administración' : 'Admin';
    const accountName = es ? 'Mi cuenta' : 'My Account';
    await page.goto('/login');
    await page.getByLabel(es ? 'Correo electrónico' : 'Email', { exact: true }).fill(state.user.email);
    await page.getByLabel(es ? 'Contraseña' : 'Password', { exact: true }).fill('SyntheticTestPassword1!');
    await page.getByRole('button', { name: es ? 'Iniciar sesión' : 'Sign In', exact: true }).click();
    await expect(page).toHaveURL(/\/map/);
    await page.locator('.user-menu__trigger').click();
    const menu = page.locator('#user-menu-dropdown');
    await expect(menu.getByRole('link', { name: adminName, exact: true })).toHaveAttribute('href', '/admin');
    expect(await menu.locator('.user-menu__items').evaluate(element => Array.from(element.children).map(child => child.textContent))).toEqual([
      accountName, adminName, expect.stringContaining(es ? 'Idioma' : 'Language'), es ? 'Cerrar sesión' : 'Sign Out',
    ]);
    const bounds = (await menu.boundingBox())!;
    expect(bounds.x).toBeGreaterThanOrEqual(0); expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    if (width === 390) for (const row of await menu.locator('.user-menu__item, select').all()) expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await page.screenshot({ path: testInfo.outputPath('admin-menu-after-login.png') });
    await menu.getByRole('link', { name: accountName, exact: true }).click();
    // The profile response publishes current permissions without reloading the app.
    state.user.roles = []; state.user.scopes = [];
    await page.getByLabel(es ? 'Nombre' : 'First name', { exact: true }).fill('Synthetic updated');
    await page.getByRole('button', { name: es ? 'Guardar perfil' : 'Save profile' }).click();
    await expect(page.getByRole('status')).toHaveText(es ? 'Guardado' : 'Saved');
    await page.locator('.user-menu__trigger').click();
    await expect(menu.getByRole('link', { name: adminName, exact: true })).toHaveCount(0);
    state.user.roles = ['admin']; state.user.scopes = ['users:write'];
    await menu.getByLabel(es ? 'Idioma' : 'Language').selectOption(es ? 'en' : 'es');
    await expect(menu.getByRole('link', { name: es ? 'Admin' : 'Administración', exact: true })).toBeVisible();
    await menu.getByLabel(es ? 'Language' : 'Idioma').selectOption(language);
    await menu.getByRole('link', { name: adminName, exact: true }).click();
    expect(new URL(page.url()).pathname).toBe('/admin');
    await page.goto('/admin/events?tab=events');
    // Reload initializes AuthContext from the existing session's /auth/me response.
    await page.reload();
    await page.locator('.user-menu__trigger').click();
    await menu.getByRole('link', { name: adminName, exact: true }).click();
    expect(new URL(page.url()).pathname).toBe('/admin');
    await page.locator('.user-menu__trigger').click();
    await menu.getByRole('button', { name: es ? 'Cerrar sesión' : 'Sign Out' }).click();
    await expect(page).toHaveURL(/\/login/);
  });
}
