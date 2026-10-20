import { expect, test, type Page } from '@playwright/test';

test.use({ viewport: { width: 1440, height: 1000 } });

const screenshots = '../artifacts/setup-passkey';
const userId = '11111111-1111-4111-8111-111111111111';
const challenge = Buffer.from('deterministic-browser-test-challenge').toString('base64url');

async function mockApi(page: Page, language = 'en', hasUsers = false) {
  const state = { complete: false, registrations: 0, logins: 0, rejectRegistration: false };
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    let status = 200;
    if (path === '/api/health/readiness') body = { status: 'ready' };
    else if (['/api/parameters', '/api/measurement-aggregation-capabilities', '/api/data-sources', '/api/air-quality-index/standards'].includes(path)) body = [];
    else if (path === '/api/version') body = { version: 'test' };
    else if (path === '/api/setup/status') body = { is_setup_required: !state.complete, has_users: hasUsers, default_language_code: language };
    else if (path === '/api/setup/data-sources') body = { data_sources: [{ external_api_id: 1, provider_code: 'openaq', name: 'OpenAQ', has_api_key: false, enabled: false, runnable_reason: 'configuration_required' }] };
    else if (path === '/api/setup/admin') { hasUsers = true; body = { success: true }; }
    else if (path === '/api/setup/complete') { state.complete = true; body = { success: true }; }
    else if (path === '/api/auth/login') body = { access_token: 'enrollment-token' };
    else if (path === '/api/auth/passkeys/register/options') body = {
      challenge, rp: { id: new URL(page.url()).hostname, name: 'CompassAQ' },
      user: { id: Buffer.from(userId).toString('base64url'), name: 'admin@example.com', displayName: 'admin@example.com' },
      pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
      authenticatorSelection: { residentKey: 'required', userVerification: 'required' }, attestation: 'none',
    };
    else if (path === '/api/auth/passkeys/register/verify') {
      expect(route.request().headers().authorization).toBe('Bearer enrollment-token');
      const credential = route.request().postDataJSON().credential;
      expect(credential.response.attestationObject).toBeTruthy();
      expect(credential.response.clientDataJSON).toBeTruthy();
      if (state.rejectRegistration) { status = 503; body = { detail: 'SECRET authenticator diagnostics' }; }
      else { state.registrations++; body = { success: true }; }
    } else if (path === '/api/auth/passkeys/login/options') body = { challenge, rpId: new URL(page.url()).hostname, userVerification: 'required', allowCredentials: [] };
    else if (path === '/api/auth/passkeys/login/verify') {
      const payload = route.request().postDataJSON();
      expect(payload.password).toBeUndefined();
      expect(payload.credential.response.signature).toBeTruthy();
      state.logins++;
      body = { access_token: 'passkey-session' };
    } else if (path === '/api/auth/me') body = { user_id: userId, email: 'admin@example.com', org_id: userId, roles: ['admin'], scopes: ['admin'], preferred_language_code: language, system_default_language_code: language };
    else { status = 401; }
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  });
  return state;
}

async function virtualAuthenticator(page: Page) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', { options: {
    protocol: 'ctap2', transport: 'internal', hasResidentKey: true,
    hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true,
  } });
  return cdp;
}

async function startAdmin(page: Page, spanish = false) {
  await page.goto('/');
  await page.getByRole('button', { name: spanish ? 'Continuar' : 'Continue', exact: true }).click();
  await page.locator('#admin-email').fill('admin@example.com');
  await page.locator('#admin-password').fill('StrongPassword1!');
  await page.locator('#admin-confirm-password').fill('StrongPassword1!');
}

async function capture(page: Page, name: string) {
  await page.evaluate(() => document.querySelector('.setup-wizard-overlay')?.scrollTo(0, 0));
  await page.screenshot({ path: `${screenshots}/${name}.png`, animations: 'disabled', fullPage: true });
  const hasScroll = await page.locator('.setup-wizard-overlay').evaluate((el) => el.scrollHeight > el.clientHeight);
  if (hasScroll) {
    await page.locator('.setup-wizard-overlay').evaluate((el) => el.scrollTo(0, el.scrollHeight));
    await page.screenshot({ path: `${screenshots}/${name}-actions.png`, animations: 'disabled', fullPage: true });
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

for (const size of [{ width: 1440, height: 1000, lang: 'en' }, { width: 820, height: 1180, lang: 'en' }, { width: 390, height: 844, lang: 'es' }]) {
  test(`secure page matches neighboring pages ${size.width} ${size.lang}`, async ({ page }) => {
    await page.setViewportSize(size);
    await mockApi(page, size.lang);
    await virtualAuthenticator(page);
    const spanish = size.lang === 'es';
    await startAdmin(page, spanish);
    await capture(page, `admin-${size.lang}-${size.width}x${size.height}`);
    const beforeWidth = await page.locator('.setup-wizard-container').evaluate((el) => el.getBoundingClientRect().width);
    await page.locator('button[type="submit"]').click();
    await expect(page.getByRole('heading', { name: spanish ? 'Proteja su cuenta de administrador' : 'Protect your administrator account' })).toBeVisible();
    const create = page.getByRole('button', { name: spanish ? 'Crear una clave de acceso' : 'Create a passkey', exact: true });
    await create.focus();
    await expect(create).toBeFocused();
    expect(await create.evaluate((el) => getComputedStyle(el).outlineStyle)).not.toBe('none');
    await capture(page, `secure-${size.lang}-${size.width}x${size.height}`);
    expect(await page.locator('.setup-wizard-container').evaluate((el) => el.getBoundingClientRect().width)).toBe(beforeWidth);
    const skip = page.getByRole('button', { name: spanish ? 'Configurar más adelante' : 'Set up later' });
    await skip.focus();
    await expect(skip).toBeFocused();
    await skip.press('Enter');
    await expect(page.getByRole('heading', { name: spanish ? 'Configurar fuente de datos' : 'Configure Data Source' })).toBeVisible();
    await capture(page, `datasource-${size.lang}-${size.width}x${size.height}`);
  });
}

test('virtual passkey registration, completion and later password-free autofill sign-in', async ({ page }) => {
  const state = await mockApi(page);
  await virtualAuthenticator(page);
  // Automatically select the virtual credential instead of interacting with browser chrome.
  await page.addInitScript(() => {
    const get = navigator.credentials.get.bind(navigator.credentials);
    navigator.credentials.get = (options) => get({ ...options, mediation: 'optional' });
  });
  await startAdmin(page);
  await page.locator('button[type="submit"]').click();
  await page.getByRole('button', { name: 'Create a passkey', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Configure Data Source' })).toBeVisible();
  expect(state.registrations).toBe(1);
  await page.getByRole('button', { name: /Skip for Now/ }).click();
  await page.getByRole('button', { name: /Skip for Now/ }).click();
  await page.getByRole('button', { name: /Complete Setup/ }).click();
  await page.goto('/login');
  await expect.poll(() => state.logins).toBe(1);
  await expect(page).toHaveURL(/\/map/);
});

for (const failure of ['cancelled', 'unsupported', 'server']) {
  test(`${failure} is friendly and permits skipping`, async ({ page }) => {
    const state = await mockApi(page);
    await virtualAuthenticator(page);
    if (failure === 'unsupported') await page.addInitScript(() => {
      PublicKeyCredential.isConditionalMediationAvailable = async () => false;
    });
    if (failure === 'cancelled') await page.addInitScript(() => {
      navigator.credentials.create = async () => { throw new DOMException('SECRET credential details', 'NotAllowedError'); };
    });
    state.rejectRegistration = failure === 'server';
    await startAdmin(page);
    await page.locator('button[type="submit"]').click();
    await page.getByRole('button', { name: 'Create a passkey', exact: true }).click();
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page.locator('body')).not.toContainText('SECRET');
    await expect(page.getByRole('button', { name: 'Create a passkey', exact: true })).toBeEnabled();
    await capture(page, `secure-${failure}-en-desktop`);
    await page.getByRole('button', { name: 'Set up later' }).click();
    await expect(page.getByRole('heading', { name: 'Configure Data Source' })).toBeVisible();
  });
}

test('reload after administrator creation skips security page', async ({ page }) => {
  await mockApi(page);
  await startAdmin(page);
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole('heading', { name: 'Protect your administrator account' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Configure Data Source' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Protect your administrator account' })).toHaveCount(0);
});
