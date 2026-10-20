import { execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

import { expect, test } from '@playwright/test';

const acceptanceUrl = process.env.DEF001_ACCEPTANCE_BASE_URL;
const composeProject = process.env.DEF001_COMPOSE_PROJECT;
const apiContainer = process.env.DEF001_API_CONTAINER;
const databaseName = process.env.DEF001_DATABASE_NAME;
const enabled = process.env.DEF001_CLEAN_INSTALL_ACCEPTANCE === '1'
  && Boolean(acceptanceUrl && composeProject && apiContainer && databaseName);

test.skip(!enabled, 'Requires the isolated DEF-001 clean-install Compose project');

function resetIsolatedDatabase() {
  if (!composeProject || !apiContainer) throw new Error('DEF-001 Compose project is not configured.');
  if (!composeProject.startsWith('compassaq-def001-qa-') || !apiContainer.startsWith(`${composeProject}-api-`)) {
    throw new Error('Refusing to reset a database outside the dedicated DEF-001 Compose project.');
  }

  const labels = JSON.parse(execFileSync('docker', [
    'inspect',
    '--format={{json .Config.Labels}}',
    apiContainer,
  ], { encoding: 'utf8' }));
  if (labels['com.docker.compose.project'] !== composeProject) {
    throw new Error(`Container ${apiContainer} does not belong to ${composeProject}.`);
  }

  const [database] = JSON.parse(execFileSync('docker', ['inspect', `${composeProject}-db-1`], { encoding: 'utf8' }));
  if (database.Config.Labels['com.docker.compose.project'] !== composeProject
      || !database.Config.Env.includes(`POSTGRES_DB=${databaseName}`)
      || !database.Mounts.some((mount: { Type: string; Name: string }) => (
        mount.Type === 'volume' && mount.Name.startsWith(`${composeProject}_`)
      ))) {
    throw new Error('Refusing to reset an unverified disposable PostgreSQL database.');
  }

  execFileSync('docker', [
    'exec',
    apiContainer,
    'python',
    '-c',
    `
from db import engine
from sqlalchemy import text
import subprocess, sys
assert engine.url.host == 'db' and engine.url.database == sys.argv[1]
with engine.begin() as connection:
    connection.execute(text('DROP SCHEMA public CASCADE'))
    connection.execute(text('CREATE SCHEMA public'))
subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True, capture_output=True)
`,
    databaseName!,
  ], { encoding: 'utf8', stdio: 'pipe' });
}

for (const language of ['en', 'es'] as const) {
  for (const width of [1440, 390] as const) {
    const height = width === 390 ? 844 : 1000;
    const spanish = language === 'es';
    const localizedError = spanish
      ? 'Ingrese una dirección de correo electrónico válida, por ejemplo, nombre@ejemplo.com.'
      : 'Enter a valid email address, such as name@example.com.';

    test(`real setup recovers from invalid email in ${language} at ${width}px`, async ({ browser }, testInfo) => {
      resetIsolatedDatabase();
      if (!acceptanceUrl || !composeProject) throw new Error('DEF-001 acceptance URL is not configured.');

      const context = await browser.newContext({
        locale: spanish ? 'es-ES' : 'en-US',
        viewport: { width, height },
        isMobile: width === 390,
        hasTouch: width === 390,
        ...(width === 390 ? { deviceScaleFactor: 2 } : {}),
      });
      const page = await context.newPage();
      let setupAdminPostCount = 0;
      page.on('request', request => {
        if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/setup/admin')) {
          setupAdminPostCount += 1;
        }
      });

      try {
        await page.addInitScript(lang => localStorage.setItem('compassaq.language', lang), language);
        await page.goto(acceptanceUrl);
        await expect(page.getByRole('heading', { name: spanish ? 'Bienvenido a CompassAQ' : 'Welcome to CompassAQ' })).toBeVisible();
        await page.getByRole('button', { name: spanish ? 'Continuar' : 'Continue', exact: true }).focus();
        await page.keyboard.press('Enter');

        const email = page.locator('#admin-email');
        await expect(email).toBeFocused();
        await email.fill('not-an-email');
        await page.keyboard.press('Enter');

        await expect(page.getByRole('heading', { name: spanish ? 'Crear cuenta de administrador' : 'Create Admin Account' })).toBeVisible();
        await expect(email).toBeFocused();
        await expect(email).toHaveValue('not-an-email');
        expect(await email.evaluate(input => input.validity.typeMismatch)).toBe(true);
        await expect(email).toHaveAttribute('aria-invalid', 'true');
        await expect(email).toHaveAttribute('aria-describedby', 'admin-email-error');
        await expect(page.getByRole('alert')).toHaveText(localizedError);
        await expect(page.getByRole('alert')).toHaveCount(1);
        expect(setupAdminPostCount).toBe(0);

        const screenshotDirectory = path.resolve(process.cwd(), '..', 'artifacts', 'def-001', 'after');
        await mkdir(screenshotDirectory, { recursive: true });
        const screenshotPath = path.join(screenshotDirectory, `invalid-email-${language}-${width}.png`);
        await page.screenshot({ path: screenshotPath, fullPage: true });
        await testInfo.attach(`invalid-email-${language}-${width}`, {
          path: screenshotPath,
          contentType: 'image/png',
        });

        const invalidBackendResponse = await page.request.post(`${acceptanceUrl}/api/setup/admin`, {
          data: {
            email: 'not-an-email',
            password: 'SetupAcceptancePassphrase2026!Strong',
            confirm_password: 'SetupAcceptancePassphrase2026!Strong',
          },
        });
        const invalidBackendBody = await invalidBackendResponse.json();
        expect(invalidBackendResponse.status()).toBe(422);
        expect(invalidBackendBody.detail[0].loc).toEqual(['body', 'email']);
        expect(setupAdminPostCount).toBe(0);

        await email.fill('installer@example.org');
        await expect(page.getByRole('alert')).toHaveCount(0);
        await expect(email).not.toHaveAttribute('aria-invalid');

        const password = page.locator('#admin-password');
        const confirmPassword = page.locator('#admin-confirm-password');
        await page.keyboard.press('Tab');
        await expect(password).toBeFocused();
        await password.fill('SetupAcceptancePassphrase2026!Strong');
        await page.keyboard.press('Tab');
        await expect(page.locator('.password-input-wrapper').nth(0).getByRole('button')).toBeFocused();
        await page.keyboard.press('Tab');
        await expect(confirmPassword).toBeFocused();
        await confirmPassword.fill('SetupAcceptancePassphrase2026!Strong');
        await page.keyboard.press('Tab');
        await page.keyboard.press('Tab');

        const createAdminButton = page.getByRole('button', {
          name: spanish ? 'Crear cuenta de administrador' : 'Create Admin Account',
        });
        await expect(createAdminButton).toBeFocused();

        // Original P1-02: valid to the browser, rejected by server email policy.
        await email.fill('qa.jordan@example.invalid');
        expect(await email.evaluate(input => input.validity.valid)).toBe(true);
        const rejectedResponsePromise = page.waitForResponse(response => (
          response.url().endsWith('/setup/admin') && response.request().method() === 'POST'
        ));
        await createAdminButton.focus();
        await page.keyboard.press('Enter');
        const rejectedResponse = await rejectedResponsePromise;
        expect(rejectedResponse.status()).toBe(422);
        const rejectedBody = await rejectedResponse.json();
        expect(rejectedBody.detail[0].loc).toEqual(['body', 'email']);
        expect(rejectedBody.detail[0].type).toBe('value_error');
        expect(rejectedResponse.request().postDataJSON().email).toBe('qa.jordan@example.invalid');
        await expect(email).toHaveValue('qa.jordan@example.invalid');
        await expect(password).toHaveValue('SetupAcceptancePassphrase2026!Strong');
        await expect(confirmPassword).toHaveValue('SetupAcceptancePassphrase2026!Strong');
        await expect(email).toHaveAttribute('aria-invalid', 'true');
        await expect(email).toHaveAttribute('aria-describedby', 'admin-email-error');
        await expect(email).toHaveAccessibleDescription(localizedError);
        await expect(page.getByRole('alert')).toHaveText(localizedError);
        await expect(email).toBeFocused();
        await expect(page.getByRole('heading', { name: spanish ? 'Crear cuenta de administrador' : 'Create Admin Account' })).toBeVisible();
        expect(setupAdminPostCount).toBe(1);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        const backendScreenshot = path.join(screenshotDirectory, `p1-02-${language}-${width}.png`);
        await page.screenshot({ path: backendScreenshot, fullPage: true });
        await testInfo.attach(`p1-02-${language}-${width}`, { path: backendScreenshot, contentType: 'image/png' });

        await email.fill('  installer@example.org  ');
        await expect(page.getByRole('alert')).toHaveCount(0);
        await expect(email).not.toHaveAttribute('aria-invalid');
        await page.keyboard.press('Tab');
        await expect(password).toBeFocused();
        await createAdminButton.focus();
        const createAdminResponsePromise = page.waitForResponse(response => (
          response.url().endsWith('/setup/admin') && response.request().method() === 'POST'
        ));
        await page.keyboard.press('Enter');
        const createAdminResponse = await createAdminResponsePromise;
        const createAdminBody = await createAdminResponse.json();
        expect(createAdminResponse.status()).toBe(200);
        expect(createAdminBody.success).toBe(true);
        expect(createAdminBody.email).toBe('installer@example.org');
        expect(setupAdminPostCount).toBe(2);

        const existingAdminResponse = await page.request.post(`${acceptanceUrl}/api/setup/admin`, {
          data: {
            email: 'another-installer@example.org',
            password: 'SetupAcceptancePassphrase2026!Strong',
            confirm_password: 'SetupAcceptancePassphrase2026!Strong',
          },
        });
        const existingAdminBody = await existingAdminResponse.json();
        expect(existingAdminResponse.status()).toBe(409);
        expect(existingAdminBody.detail.error_code).toBe('setup_admin_already_created');

        await page.getByRole('button', { name: spanish ? 'Configurar más adelante' : 'Set up later' }).click();
        await page.getByRole('button', { name: spanish ? 'Guardar fuentes y continuar' : 'Save Sources & Continue' }).click();
        await page.getByRole('button', { name: spanish ? 'Saltar por ahora →' : 'Skip for Now →' }).click();
        const completionResponsePromise = page.waitForResponse(response => (
          response.url().endsWith('/setup/complete') && response.request().method() === 'POST'
        ));
        const setupReload = page.waitForEvent('framenavigated', {
          predicate: frame => frame === page.mainFrame(),
        });
        await page.getByRole('button', {
          name: spanish ? 'Complete la configuración y comience a usar la plataforma' : 'Complete Setup & Start Using Platform',
        }).click();
        const completionResponse = await completionResponsePromise;
        expect(completionResponse.status()).toBe(200);
        await setupReload;
        await page.waitForLoadState('domcontentloaded');

        await page.goto(`${acceptanceUrl}/login`);
        const persistedStatus = await page.request.get(`${acceptanceUrl}/api/setup/status`);
        expect(await persistedStatus.json()).toEqual({
          is_setup_required: false, has_users: true, default_language_code: language,
        });
        await page.locator('input[type="email"]').fill('installer@example.org');
        await page.locator('input[type="password"]').fill('SetupAcceptancePassphrase2026!Strong');
        const loginResponsePromise = page.waitForResponse(response => response.url().endsWith('/auth/login'));
        await page.getByRole('button', { name: spanish ? 'Iniciar sesión' : 'Sign In', exact: true }).click();
        const loginResponse = await loginResponsePromise;
        expect(loginResponse.status()).toBe(200);
        await expect(page).toHaveURL(/\/map/);

        const evidence = {
          language,
          viewport: `${width}x${height}`,
          invalidInput: 'not-an-email',
          invalidAttemptApiPosts: 0,
          invalidAttemptBackendValidationStatus: invalidBackendResponse.status(),
          invalidAttemptBackendValidationBody: invalidBackendBody,
          fieldError: localizedError,
          originalInput: 'qa.jordan@example.invalid',
          browserValidity: { valid: true, typeMismatch: false },
          originalBackendStatus: rejectedResponse.status(),
          originalBackendValidation: rejectedBody.detail.map(({ loc, type }: { loc: string[]; type: string }) => ({ loc, type })),
          originalRequest: { email: 'qa.jordan@example.invalid', password: '[REDACTED]', confirm_password: '[REDACTED]' },
          fieldInvalid: 'true',
          fieldDescribedBy: 'admin-email-error',
          focusAfterRejection: 'admin-email',
          valuesPreserved: true,
          backendScreenshot,
          createAdminStatus: createAdminResponse.status(),
          createAdminEmail: createAdminBody.email,
          secondAdminConflictStatus: existingAdminResponse.status(),
          secondAdminErrorCode: existingAdminBody.detail.error_code,
          setupCompletionStatus: completionResponse.status(),
          loginStatus: loginResponse.status(),
          screenshotPath,
          composeProject,
        };
        await writeFile(
          path.join(screenshotDirectory, `invalid-email-${language}-${width}.json`),
          JSON.stringify(evidence, null, 2),
        );
        await testInfo.attach(`acceptance-${language}-${width}.json`, {
          body: Buffer.from(JSON.stringify(evidence, null, 2)),
          contentType: 'application/json',
        });
      } finally {
        await context.close();
      }
    });
  }
}
