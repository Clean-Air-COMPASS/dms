import { expect, test } from '@playwright/test';
import { mockAdministration, stamp } from './fixtures/administration';
import en from '../src/i18n/locales/en/emailNotifications.json' with { type: 'json' };
import es from '../src/i18n/locales/es/emailNotifications.json' with { type: 'json' };

for (const language of ['en', 'es'] as const) {
  for (const width of [1440, 390]) {
    for (const scenario of ['unconfigured', 'untested', 'ready', 'summary', 'error'] as const) {
      test(`Email workflow ${scenario} ${language} ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
        const state = await mockAdministration(page, language);
        const copy = language === 'en' ? en : es;
        if (scenario === 'unconfigured') {
          Object.assign(state.email, {
            enabled: false, status: 'not_configured', status_reason_codes: ['email_not_configured'],
            smtp_host: null, smtp_port: null, smtp_security_mode: null, smtp_username: null,
            password_configured: false, from_email: null, from_display_name: null,
            administrator_recipients: [], last_test_status: null, last_tested_at: null,
          });
        } else if (scenario === 'untested') {
          Object.assign(state.email, {
            status: 'needs_attention', status_reason_codes: ['test_required'],
            last_test_status: null, last_tested_at: null,
          });
        } else if (scenario === 'error') {
          Object.assign(state.email, {
            status: 'needs_attention', status_reason_codes: ['smtp_authentication_failed'],
            last_test_status: 'failed', last_test_error_code: 'smtp_authentication_failed',
          });
        } else if (scenario === 'summary') {
          Object.assign(state.summary, {
            enabled: true, schedule_status: 'last_summary_sent', next_due_at: '2026-09-06T07:00:00Z',
            next_reporting_window: { period_start: '2026-09-05T00:00:00Z', period_end: '2026-09-06T00:00:00Z' },
            last_scheduled_delivery: {
              status: 'sent', period_start: '2026-09-04T00:00:00Z', period_end: '2026-09-05T00:00:00Z',
              sent_at: stamp, last_attempted_at: stamp, error_code: null,
            },
          });
        }
        state.summary.email_delivery_ready = ['ready', 'summary'].includes(scenario);
        await page.goto('/admin/email');
        await expect(page.getByRole('heading', { name: copy.workflow.activityTitle })).toBeVisible();
        await expect(page.locator('.email-admin-page h2')).toHaveText([
          copy.workflow.deliveryTitle, copy.test.title, copy.administratorSummary.title, copy.workflow.activityTitle,
        ]);
        await expect(page.locator('.email-fact-grid, .admin-section-links')).toHaveCount(0);
        const action = scenario === 'unconfigured' ? copy.workflow.configure
          : scenario === 'untested' ? copy.workflow.test
            : scenario === 'error' ? copy.workflow.retry
              : scenario === 'summary' ? copy.workflow.monitor : copy.workflow.summary;
        await expect(page.locator('.email-next-action')).toContainText(action);
        const testAction = page.getByRole('button', { name: copy.test.sendAction, exact: true });
        if (scenario === 'unconfigured') await expect(testAction).toBeDisabled();
        else await expect(testAction).toBeEnabled();
        const firstAction = scenario === 'unconfigured'
          ? page.getByLabel(copy.form.delivery.enabledLabel)
          : page.getByRole('button', { name: copy.actions.edit });
        expect((await firstAction.boundingBox())!.y).toBeLessThan(700);
        if (scenario === 'unconfigured') {
          expect((await page.getByLabel(copy.form.smtp.hostLabel).boundingBox())!.y).toBeLessThan(820);
        }
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
        await page.screenshot({ path: `../artifacts/email-workflow/${scenario}-${language}-${width}.png`, fullPage: true });

        if (scenario === 'ready') {
          await firstAction.focus();
          await page.keyboard.press('Enter');
          await expect(page.getByLabel(copy.form.delivery.enabledLabel)).toBeFocused();
          const displayName = page.getByLabel(copy.form.sender.displayNameLabel);
          await displayName.fill('CompassAQ updated');
          await page.locator('.email-configuration-form').getByRole('button', { name: copy.actions.save, exact: true }).click();
          await expect(page.getByRole('status')).toHaveText(copy.messages.saved);
          await expect(page.getByRole('status')).toBeFocused();
          await testAction.focus();
          await page.keyboard.press('Enter');
          await expect(page.locator('.email-test-result')).toBeFocused();
          await expect(page.locator('.email-test-result')).toContainText('administrator@example.org');
        }
      });
    }
  }
}
