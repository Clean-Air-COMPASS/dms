import { expect, test, type Page, type TestInfo } from '@playwright/test';

type Language = 'en' | 'es';

const languageCopy: Record<Language, { label: string; mapLink: string }> = {
  en: { label: 'Language', mapLink: 'Open Map' },
  es: { label: 'Idioma', mapLink: 'Abrir mapa' },
};

async function mockHomeDependencies(page: Page): Promise<void> {
  await page.addInitScript(() => {
    window.localStorage.setItem('compassaq.language', 'en');
  });

  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, '');

    if (path === '/health/readiness') {
      await route.fulfill({ json: { status: 'ready' } });
    } else if (path === '/setup/status') {
      await route.fulfill({
        json: { is_setup_required: false, has_users: true, default_language_code: 'en' },
      });
    } else if (path === '/auth/refresh') {
      await route.fulfill({ status: 401, json: {} });
    } else if (path === '/version') {
      await route.fulfill({ json: { postgres_version: 'browser-test' } });
    } else {
      await route.fulfill({ json: [] });
    }
  });
}

function contrastRatio(foreground: string, background: string): number {
  const luminance = (color: string) => {
    const channels = color.match(/[\d.]+/g)?.slice(0, 3).map(Number);
    if (!channels || channels.length !== 3) throw new Error(`Unexpected CSS color: ${color}`);

    const linearChannels = channels.map((channel) => {
      const normalized = channel / 255;
      return normalized <= 0.04045
        ? normalized / 12.92
        : ((normalized + 0.055) / 1.055) ** 2.4;
    });

    return (0.2126 * linearChannels[0]) + (0.7152 * linearChannels[1]) + (0.0722 * linearChannels[2]);
  };

  const foregroundLuminance = luminance(foreground);
  const backgroundLuminance = luminance(background);
  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

async function expectReadableHover(selector: ReturnType<Page['locator']>): Promise<void> {
  const style = await selector.evaluate((element) => {
    const computed = getComputedStyle(element);
    return {
      color: computed.color,
      background: computed.backgroundColor,
      colorScheme: computed.colorScheme,
      hovered: element.matches(':hover'),
    };
  });

  expect(style.hovered).toBe(true);
  expect(style.colorScheme).toBe('light');
  expect(contrastRatio(style.color, style.background)).toBeGreaterThanOrEqual(4.5);
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const dimensions = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }));

  expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
  expect(dimensions.bodyWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
}

async function captureState(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: false });
}

for (const colorScheme of ['light', 'dark'] as const) for (const [width, height] of [[1440, 900], [390, 844]] as const) {
  test(`Home language selector stays readable and keyboard accessible at ${width}px in ${colorScheme} scheme`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ colorScheme });
    await mockHomeDependencies(page);
    await page.goto('/');

    await expect(page.locator('.landing-page')).toBeVisible();
    const selector = page.locator('#landing-language-selector');
    await expect(selector).toBeVisible();
    await expect(selector).toBeEnabled();
    await expect(selector).toHaveValue('en');
    await expect(selector.locator('option')).toHaveCount(2);
    await expect(selector.locator('option')).toHaveText(['English', 'Español']);
    await expect(page.getByRole('combobox', { name: languageCopy.en.label })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await captureState(page, testInfo, `en-${width}-normal`);

    await selector.hover();
    await expectReadableHover(selector);
    await expectNoHorizontalOverflow(page);
    await captureState(page, testInfo, `en-${width}-hover`);

    await page.mouse.down();
    await expect.poll(() => selector.evaluate((element) => element.matches(':active'))).toBe(true);
    await expectReadableHover(selector);
    await captureState(page, testInfo, `en-${width}-active`);
    await page.mouse.up();
    await page.keyboard.press('Escape');

    await selector.blur();
    await page.mouse.move(1, height - 1);
    await page.getByRole('link', { name: languageCopy.en.mapLink, exact: true }).focus();
    await page.keyboard.press('Shift+Tab');
    await expect(selector).toBeFocused();
    const focusStyle = await selector.evaluate((element) => {
      const computed = getComputedStyle(element);
      return {
        visible: element.matches(':focus-visible'),
        outlineStyle: computed.outlineStyle,
        outlineWidth: computed.outlineWidth,
        outlineColor: computed.outlineColor,
        background: computed.backgroundColor,
      };
    });
    expect(focusStyle.visible).toBe(true);
    expect(focusStyle.outlineStyle).toBe('solid');
    expect(focusStyle.outlineWidth).toBe('2px');
    expect(contrastRatio(focusStyle.outlineColor, focusStyle.background)).toBeGreaterThanOrEqual(3);
    await captureState(page, testInfo, `en-${width}-focus`);

    await page.keyboard.press('ArrowDown');
    await expect(selector).toHaveValue('es');
    await expect(selector).toBeFocused();
    expect(await selector.evaluate((element) => element.matches(':focus-visible'))).toBe(true);
    await expect.poll(() => page.evaluate(() => document.documentElement.lang)).toBe('es');
    await expect(page.getByRole('combobox', { name: languageCopy.es.label })).toBeVisible();
    await expect(page.getByRole('link', { name: languageCopy.es.mapLink, exact: true })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await captureState(page, testInfo, `es-${width}-focus`);

    await selector.blur();
    await page.mouse.move(1, height - 1);
    await captureState(page, testInfo, `es-${width}-normal`);

    await selector.hover();
    await expectReadableHover(selector);
    await expectNoHorizontalOverflow(page);
    await captureState(page, testInfo, `es-${width}-hover`);

    await page.mouse.down();
    await expect.poll(() => selector.evaluate((element) => element.matches(':active'))).toBe(true);
    await expectReadableHover(selector);
    await captureState(page, testInfo, `es-${width}-active`);
    await page.mouse.up();
    await page.keyboard.press('Escape');

    await selector.blur();
    await page.mouse.move(1, height - 1);
    await page.getByRole('link', { name: languageCopy.es.mapLink, exact: true }).focus();
    await page.keyboard.press('Shift+Tab');
    await expect(selector).toBeFocused();
    await page.keyboard.press('ArrowUp');
    await expect(selector).toHaveValue('en');
    await expect.poll(() => page.evaluate(() => document.documentElement.lang)).toBe('en');
    await expect(page.getByRole('combobox', { name: languageCopy.en.label })).toBeVisible();
    await expect(page.getByRole('link', { name: languageCopy.en.mapLink, exact: true })).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
}
