import { expect, test, type Page } from '@playwright/test';

type Language = 'en' | 'es';

const fixtureUser = {
  user_id: 'responsive-qa-user',
  email: 'responsive@example.org',
  first_name: 'Responsive',
  last_name: 'Tester',
  display_name: 'Responsive Tester',
  passkey_count: 0,
  org_id: 'responsive-qa-org',
  roles: ['admin'],
  scopes: ['users:write'],
};

async function mockApp(page: Page, language: Language, authenticated = false) {
  await page.addInitScript((requestedLanguage) => {
    localStorage.setItem('compassaq.language', requestedLanguage);
  }, language);

  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, '');
    let status = 200;
    let body: unknown = [];

    if (path === '/health/readiness') {
      body = { status: 'ready' };
    } else if (path === '/setup/status') {
      body = { is_setup_required: false, has_users: true, default_language_code: language };
    } else if (path === '/auth/refresh') {
      status = authenticated ? 200 : 401;
      body = authenticated ? { access_token: 'responsive-fixture-token' } : {};
    } else if (path === '/auth/me') {
      status = authenticated ? 200 : 401;
      body = authenticated
        ? {
            ...fixtureUser,
            preferred_language_code: language,
            system_default_language_code: language,
          }
        : {};
    } else if (path === '/parameters') {
      body = [{ code: 'pm25', display_name: 'PM2.5' }];
    } else if (path === '/version') {
      body = { postgres_version: 'synthetic' };
    }

    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

async function openAnalytics(page: Page, language: Language) {
  await page.goto('/analytics');
  const closeModal = page.getByRole('button', {
    name: language === 'es' ? 'Cerrar modal' : 'Close modal',
  });
  await closeModal.waitFor({ state: 'visible' });
  await closeModal.click();
}

async function expectHeaderLayout(page: Page, signInName: string, assertPageOverflow: boolean) {
  const signIn = page.getByRole('link', { name: signInName, exact: true });
  await expect(signIn).toBeVisible();
  await expect(signIn).toHaveAccessibleName(signInName);
  await expect(signIn).toHaveAttribute('href', '/login');

  const metrics = await page.evaluate(() => {
    const header = document.querySelector('header');
    const brand = header?.querySelector(':scope > a');
    const actions = header?.querySelector(':scope > div');
    const link = [...(actions?.querySelectorAll('a') ?? [])].find((item) =>
      /sign in|iniciar sesión/i.test(item.textContent ?? ''),
    );
    if (!header || !brand || !actions || !link) throw new Error('Analytics navigation is incomplete');

    const range = document.createRange();
    range.selectNodeContents(link);
    const headerRect = header.getBoundingClientRect();
    const linkRect = link.getBoundingClientRect();
    const textRects = [...range.getClientRects()].map((rect) => ({ left: rect.left, right: rect.right }));
    const actionLinks = [...actions.querySelectorAll('a')].map((item) => {
      const rect = item.getBoundingClientRect();
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
    });
    const overlaps = actionLinks.some((first, index) => actionLinks.slice(index + 1).some((second) =>
      first.left < second.right && first.right > second.left &&
      first.top < second.bottom && first.bottom > second.top,
    ));

    return {
      viewportWidth: innerWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      headerWidth: headerRect.width,
      headerScrollWidth: header.scrollWidth,
      headerClientWidth: header.clientWidth,
      actionsWidth: actions.getBoundingClientRect().width,
      actionsFlexWrap: getComputedStyle(actions).flexWrap,
      headerFlexWrap: getComputedStyle(header).flexWrap,
      headerOverflow: getComputedStyle(header).overflow,
      linkLeft: linkRect.left,
      linkRight: linkRect.right,
      textRects,
      accessibleName: link.getAttribute('aria-label') ?? link.innerText.trim(),
      actionsOverlap: overlaps,
      language: document.documentElement.lang,
    };
  });

  expect(metrics.linkLeft).toBeGreaterThanOrEqual(0);
  expect(metrics.linkRight).toBeLessThanOrEqual(metrics.viewportWidth);
  expect(metrics.textRects.length).toBeGreaterThan(0);
  for (const textRect of metrics.textRects) {
    expect(textRect.left).toBeGreaterThanOrEqual(0);
    expect(textRect.right).toBeLessThanOrEqual(metrics.viewportWidth);
  }
  expect(metrics.actionsOverlap).toBe(false);
  expect(metrics.headerScrollWidth).toBeLessThanOrEqual(metrics.headerClientWidth);
  if (assertPageOverflow) expect(metrics.documentScrollWidth).toBeLessThanOrEqual(metrics.viewportWidth);

  return { signIn, metrics };
}

for (const [language, width] of [
  ['es', 390],
  ['en', 390],
  ['es', 1440],
  ['en', 1440],
  ['es', 360],
  ['es', 320],
] as const) {
  test(`Analytics sign-in fits at ${width}px in ${language}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await mockApp(page, language);
    await openAnalytics(page, language);

    const signInName = language === 'es' ? 'Iniciar sesión' : 'Sign in';
    const { signIn, metrics } = await expectHeaderLayout(page, signInName, true);
    await testInfo.attach('analytics-header-layout.json', {
      body: Buffer.from(JSON.stringify(metrics, null, 2)),
      contentType: 'application/json',
    });
    await page.screenshot({ path: testInfo.outputPath(`analytics-sign-in-${language}-${width}.png`), fullPage: true });

    const brand = page.getByRole('link', { name: 'COMPASS', exact: true });
    await brand.focus();
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');
    await expect(signIn).toBeFocused();
    const focusStyle = await signIn.evaluate((element) => getComputedStyle(element).outlineStyle);
    expect(focusStyle).toBe('solid');
    await page.screenshot({ path: testInfo.outputPath(`analytics-sign-in-${language}-${width}-focus.png`), fullPage: true });

    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.locator('#email')).toBeVisible();
  });
}

test('Analytics sign-in navigation remains usable with Spanish text at 200% root text size', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApp(page, 'es');
  await openAnalytics(page, 'es');
  await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });

  const { metrics } = await expectHeaderLayout(page, 'Iniciar sesión', false);
  await testInfo.attach('analytics-header-layout-200-percent.json', {
    body: Buffer.from(JSON.stringify(metrics, null, 2)),
    contentType: 'application/json',
  });
  await page.screenshot({ path: testInfo.outputPath('analytics-sign-in-es-390-200-percent-text.png'), fullPage: true });
});

for (const language of ['en', 'es'] as const) {
  test(`Analytics authenticated navigation remains usable in ${language}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockApp(page, language, true);
    await openAnalytics(page, language);

    const header = page.locator('header');
    await expect(header.locator('a[href="/login"]')).toHaveCount(0);
    const accountMenu = header.locator('.user-menu__trigger');
    await expect(accountMenu).toBeVisible();
    await expect(accountMenu).toHaveAccessibleName(/Responsive Tester/);
    await expect(header.locator('a[href="/admin"]')).toBeVisible();
    await expect(header.locator('a[href^="/map"]').nth(1)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await accountMenu.click();
    await expect(page.getByRole('region', { name: language === 'es' ? 'Menú de cuenta' : 'Account menu' })).toBeVisible();
    await expect(page.locator('#user-menu-dropdown a[href="/account"]')).toBeVisible();
    const dropdownBounds = await page.locator('#user-menu-dropdown').evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
    });
    expect(dropdownBounds.left).toBeGreaterThanOrEqual(0);
    expect(dropdownBounds.right).toBeLessThanOrEqual(390);
    expect(dropdownBounds.top).toBeGreaterThanOrEqual(0);
    expect(dropdownBounds.bottom).toBeLessThanOrEqual(844);
    await page.screenshot({ path: testInfo.outputPath(`analytics-authenticated-${language}-390.png`), fullPage: true });
  });
}
