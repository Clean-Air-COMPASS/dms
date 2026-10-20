import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { readFile, writeFile } from 'node:fs/promises';
import type { Chart } from 'chart.js';
import { execFileSync } from 'node:child_process';

type Observation = { timestamp: string; value: number; is_valid: boolean };
type Stream = { sensor_id: number; device_id: number; aggregation: string; observations: Observation[] };
type Fixture = { evaluation_time: string; streams: { hour: Stream; sparse: Stream } };
const fixturePath = process.env.DEV004_FIXTURE;
const fixture: Fixture | null = fixturePath ? JSON.parse(readFileSync(fixturePath, 'utf8')) : null;
const baseline = process.env.DEV004_BASELINE === '1';
const qaBaseUrl = process.env.QC_E2E_BASE_URL;
const expectedProject = process.env.DEV004_EXPECTED_PROJECT;
test.skip(!fixture, 'Set DEV004_FIXTURE to the isolated seed output.');

test.beforeAll(() => {
  if (!qaBaseUrl) throw new Error('Set QC_E2E_BASE_URL to the explicit isolated QA browser URL.');
  if (!expectedProject) throw new Error('Set DEV004_EXPECTED_PROJECT to the isolated Compose project identity.');
  const browserUrl = new URL(qaBaseUrl);
  expect(browserUrl.protocol).toBe('http:');
  expect(browserUrl.hostname).toBe('127.0.0.1');
  expect(browserUrl.port).not.toBe('');
  expect(browserUrl.port).not.toBe('80');
  expect(expectedProject).toMatch(/^compassaq-dev004-[a-z0-9-]+$/);
  for (const service of ['api', 'db', 'frontend']) {
    const containerName = `${expectedProject}-${service}-1`;
    const [container] = JSON.parse(execFileSync('docker', ['inspect', containerName], { encoding: 'utf8' }));
    expect(container.Name).toBe(`/${containerName}`);
    expect(container.Config.Labels['com.docker.compose.project']).toBe(expectedProject);
    expect(container.State.Running).toBe(true);
    expect(Object.keys(container.NetworkSettings.Networks)).toEqual([`${expectedProject}_default`]);
    for (const mount of container.Mounts) {
      if (mount.Type === 'volume') expect(mount.Name).toMatch(new RegExp(`^${expectedProject}_`));
    }
    if (service === 'api') {
      expect(container.Config.Env.some((entry: string) => /^DATABASE_URL=postgresql\+psycopg:\/\/dev004:[^@]+@db:5432\/dev004_qa$/.test(entry))).toBe(true);
      const apiPorts = Object.values(container.NetworkSettings.Ports).flatMap((ports: { HostIp: string; HostPort: string }[] | null) => ports ?? []);
      expect(apiPorts).toHaveLength(1);
      expect(apiPorts[0].HostIp).toBe('127.0.0.1');
    }
    if (service === 'db') expect(Object.values(container.NetworkSettings.Ports).flatMap((ports: unknown[] | null) => ports ?? [])).toHaveLength(0);
    if (service === 'frontend') expect(container.NetworkSettings.Ports['80/tcp']).toEqual([{ HostIp: '127.0.0.1', HostPort: browserUrl.port }]);
  }
});

async function chartState(page: Page) {
  return page.locator('.sensor-chart canvas').evaluate(element => {
    type Hook = { memoizedState?: { current?: Chart }; next?: Hook };
    type Fiber = { memoizedState?: Hook; return?: Fiber };
    const key = Object.keys(element).find(key => key.startsWith('__reactFiber'))!;
    let fiber = (element as unknown as Record<string, Fiber>)[key];
    while (fiber) {
      let hook = fiber.memoizedState;
      while (hook) {
        const chart = hook.memoizedState?.current;
        if (chart?.canvas === element && chart.getDatasetMeta(0).data.length) {
          return {
            points: chart.data.datasets[0].data,
            markers: chart.getDatasetMeta(0).data.map(point => ({
              x: point.x, y: point.y,
              radius: (point.options as { radius?: number }).radius,
              style: (point.options as { pointStyle?: string }).pointStyle,
            })),
            min: chart.scales.x.min, max: chart.scales.x.max,
            segments: (chart.getDatasetMeta(0).dataset as unknown as { segments: { start: number; end: number; style?: { borderColor?: string } }[] }).segments,
            tooltip: chart.tooltip?.body?.flatMap(body => body.lines).join(' ') ?? '',
          };
        }
        hook = hook.next;
      }
      fiber = fiber.return!;
    }
    throw new Error('Mounted chart unavailable');
  });
}

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`DEV-004 real relative and explicit history ${language} ${width}`, async ({ page }, info) => {
    const data = fixture!;
    await page.setViewportSize({ width, height: 1000 });
    // Only external basemap tiles are replaced. All CompassAQ responses are real.
    await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({
      json: { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }] },
    }));
    await page.goto('/login');
    await page.getByLabel('Email').fill('synthetic.dev004@example.com');
    await page.getByRole('textbox', { name: 'Password' }).fill('Synthetic-DEV004-QA-only-2026!');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(/\/map/);
    if (await page.locator('html').getAttribute('lang') !== language) {
      const select = page.getByRole('combobox', { name: /^(Language|Idioma)$/ });
      if (!await select.isVisible()) await page.getByRole('button', { name: /Account menu for|Menú de cuenta/ }).click();
      await select.selectOption(language);
      await expect(page.locator('html')).toHaveAttribute('lang', language);
    }
    const evidence: unknown[] = [];
    for (const [name, stream] of Object.entries(data.streams)) {
      const before = Date.now();
      const historyPromise = page.waitForResponse(response => response.url().includes(`/sensors/${stream.sensor_id}/history?`));
      await page.goto(`/map?mode=pollutants&parameter=pm25&time_resolution=${stream.aggregation}&device_id=${stream.device_id}&lat=34.05&lng=-118.2&zoom=10`);
      const response = await historyPromise;
      expect(response.ok()).toBe(true);
      const after = Date.now();
      const payload = await response.json();
      const request = new URL(response.url());
      expect(request.searchParams.get('hours')).toBe('24');
      expect(request.searchParams.has('start')).toBe(false);
      expect(request.searchParams.has('end')).toBe(false);
      const expected = stream.observations.filter(row => row.is_valid
        && Date.parse(row.timestamp) >= after - 86400000
        && (baseline || Date.parse(row.timestamp) <= before));
      expect(payload.data.map((row: Observation) => row.value)).toEqual(expected.map(row => row.value));
      expect(payload.data.some((row: Observation) => Date.parse(row.timestamp) === Date.parse(data.evaluation_time))).toBe(true);
      expect(payload.data.some((row: Observation) => Date.parse(row.timestamp) > after)).toBe(baseline);
      await expect(page.locator('.sensor-chart canvas')).toBeVisible();
      await expect(page.getByText(language === 'es' ? 'Últimas 24 horas' : 'Last 24 Hours', { exact: false }).first()).toBeVisible();
      await expect.poll(async () => (await chartState(page)).markers.length).toBe(payload.data.length);
      const state = await chartState(page);
      expect(state.points.map(point => (point as { y: number }).y)).toEqual(expected.map(row => row.value));
      if (name === 'sparse') {
        expect(state.markers[0].radius).toBeGreaterThan(0);
        expect(state.markers.some(marker => marker.style === 'triangle')).toBe(true);
        // No rendered line segment bridges unsupported gaps in minute history.
        const points = state.points as { x: number }[];
        for (const segment of state.segments) for (let index = segment.start; index < segment.end; index++) {
          if (points[index + 1].x - points[index].x > 90_000) expect(segment.style?.borderColor).toBe('transparent');
        }
      }
      const canvas = page.locator('.sensor-chart canvas');
      await canvas.scrollIntoViewIfNeeded();
      const bounds = (await canvas.boundingBox())!;
      const marker = state.markers[0];
      await page.mouse.move(bounds.x + marker.x, bounds.y + marker.y);
      await expect.poll(async () => (await chartState(page)).tooltip).toContain('µg/m³');
      await page.screenshot({ path: info.outputPath(`map-${name}-tooltip.png`), fullPage: true });
      await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
      await page.keyboard.down('Control');
      await page.mouse.wheel(0, -200);
      await page.keyboard.up('Control');
      await expect.poll(async () => (await chartState(page)).max - (await chartState(page)).min).toBeLessThan(state.max - state.min);
      const zoomed = await chartState(page);
      await page.keyboard.down('Shift');
      await page.mouse.down();
      await page.mouse.move(bounds.x + bounds.width / 2 + 35, bounds.y + bounds.height / 2, { steps: 8 });
      await page.mouse.up();
      await page.keyboard.up('Shift');
      await expect.poll(async () => (await chartState(page)).min).not.toBe(zoomed.min);
      const reset = page.getByRole('button', { name: /Reset Zoom|Restablecer zoom/i });
      await reset.focus();
      await expect(reset).toBeFocused();
      await page.keyboard.press('Enter');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath(`map-${name}.png`), fullPage: true });
      evidence.push({ request: response.url(), before, after, payload, chart: state });
    }
    if (!baseline) {
      const details = page.locator('.slide-out-panel');
      for (const [resolution, values, counts] of [
        ['1h', [10.1, 14, 514.5], [1, 1, 2]],
        ['24h', [12.1, 514.5], [2, 2]],
      ] as const) {
        if (width === 390) await details.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click();
        const aggregationPromise = page.waitForResponse(response => response.url().includes(`/sensors/${data.streams.sparse.sensor_id}/history?`) && new URL(response.url()).searchParams.get('aggregation') === resolution);
        await page.getByLabel(/^(Time resolution|Resolución temporal)$/).selectOption(resolution);
        if (width === 390) await page.getByRole('button', { name: /^(Close controls|Cerrar controles)$/ }).click();
        const response = await aggregationPromise;
        expect(response.ok()).toBe(true);
        const payload = await response.json();
        expect(payload.data.map((row: Observation) => row.value)).toEqual(values);
        expect(payload.data.map((row: { sample_count: number }) => row.sample_count)).toEqual(counts);
        expect(payload.data.every((row: Observation) => Date.parse(row.timestamp) <= Date.now())).toBe(true);
        await expect(details.getByRole('heading', { name: 'SYNTHETIC DEV-004 sparse', exact: true })).toBeVisible();
        await expect.poll(async () => (await chartState(page)).markers.length).toBe(values.length);
        await page.screenshot({ path: info.outputPath(`map-${resolution}.png`), fullPage: true });
        evidence.push({ request: response.url(), payload });
      }
    }
    // Explicit range intentionally includes the future-dated native observations.
    const stream = data.streams.sparse;
    const start = stream.observations[0].timestamp;
    const end = stream.observations.at(-1)!.timestamp;
    const query = new URLSearchParams({ series: `measurement|${stream.sensor_id}|pm25|1m`, start, end, timezone: 'utc' });
    const analyticsPromise = page.waitForResponse(response => response.url().includes(`/sensors/${stream.sensor_id}/history?`) && response.url().includes('start='));
    await page.goto('/analytics?' + query);
    const analyticsResponse = await analyticsPromise;
    expect(analyticsResponse.ok()).toBe(true);
    const analytics = await analyticsResponse.json();
    expect(analytics.data.map((row: Observation) => row.value)).toEqual([10.123456789, 14, 30, 999, 9999]);
    await expect(page.locator('.sensor-chart canvas')).toBeVisible();
    await expect.poll(async () => (await chartState(page)).markers.length).toBe(5);
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /Download CSV|Descargar CSV/i }).click();
    const download = await downloadPromise;
    await download.saveAs(info.outputPath('explicit-range.csv'));
    const csv = await readFile(info.outputPath('explicit-range.csv'), 'utf8');
    expect(csv.trim().split(/\r?\n/)).toHaveLength(6);
    expect(csv).toContain('10.123456789');
    expect(csv).toContain('9999');
    expect(csv).toContain('µg/m³');
    await page.screenshot({ path: info.outputPath('analytics.png'), fullPage: true });
    evidence.push({ request: analyticsResponse.url(), payload: analytics, csv });

    query.set('end', data.evaluation_time);
    const boundedPromise = page.waitForResponse(response => response.url().includes(`/sensors/${stream.sensor_id}/history?`) && response.url().includes('start='));
    await page.goto('/analytics?' + query);
    const boundedResponse = await boundedPromise;
    const bounded = await boundedResponse.json();
    expect(bounded.data.map((row: Observation) => row.value)).toEqual([10.123456789, 14, 30]);
    await expect.poll(async () => (await chartState(page)).markers.length).toBe(3);
    const boundedDownloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /Download CSV|Descargar CSV/i }).click();
    await (await boundedDownloadPromise).saveAs(info.outputPath('bounded-range.csv'));
    const boundedCsv = await readFile(info.outputPath('bounded-range.csv'), 'utf8');
    expect(boundedCsv.trim().split(/\r?\n/)).toHaveLength(4);
    expect(boundedCsv).toContain('10.123456789');
    expect(boundedCsv).not.toContain('9999');
    await page.screenshot({ path: info.outputPath('analytics-bounded.png'), fullPage: true });
    const invalidPromise = page.waitForResponse(response => response.url().includes(`/sensors/${stream.sensor_id}/history?`) && response.url().includes('include_invalid=true'));
    await page.getByRole('checkbox', { name: /Include invalid measurements|Incluir mediciones no válidas/ }).check();
    const invalidResponse = await invalidPromise;
    const invalid = await invalidResponse.json();
    expect(invalid.data.map((row: Observation) => row.value)).toEqual([10.123456789, 14, 20, 30]);
    await page.getByRole('checkbox', { name: /Show invalid points|Mostrar puntos no válidos/ }).check();
    await expect.poll(async () => (await chartState(page)).markers.some(marker => marker.style === 'crossRot' && marker.radius! > 0)).toBe(true);
    await page.screenshot({ path: info.outputPath('analytics-invalid.png'), fullPage: true });
    evidence.push({ request: boundedResponse.url(), payload: bounded, csv: boundedCsv }, { request: invalidResponse.url(), payload: invalid });
    await writeFile(info.outputPath('evidence.json'), JSON.stringify(evidence, null, 2));
  });
}
