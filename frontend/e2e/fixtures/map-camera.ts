import { expect, type Page } from '@playwright/test';
import type { Map as MapLibreMap } from 'maplibre-gl';

// Inspect the mounted real MapLibre instance without adding a production test API.
export async function mapCamera(page: Page, action: 'read' | 'jump' | 'pan' = 'read', longitude = 0, latitude = 0, zoom = 0) {
  return page.locator('.map-canvas').evaluate((element, args) => {
    type Hook = { memoizedState?: { current?: MapLibreMap }; next?: Hook };
    type Fiber = { memoizedState?: Hook; return?: Fiber };
    const key = Object.keys(element).find(key => key.startsWith('__reactFiber'))!;
    let fiber = (element as unknown as Record<string, Fiber>)[key];
    let map: MapLibreMap | undefined;
    while (fiber && !map) {
      let hook = fiber.memoizedState;
      while (hook && !map) {
        const current = hook.memoizedState?.current;
        if (current && typeof current.getCenter === 'function') map = current;
        hook = hook.next;
      }
      fiber = fiber.return!;
    }
    if (!map) throw new Error('Mounted MapLibre ref not found');
    if (args.action === 'jump') map.jumpTo({ center: [args.longitude, args.latitude], zoom: args.zoom });
    if (args.action === 'pan') map.panBy([args.longitude, args.latitude], { duration: 0 });
    const center = map.getCenter();
    return {
      lng: center.lng, lat: center.lat, zoom: map.getZoom(), loaded: map.loaded(),
      width: map.getCanvas().clientWidth, height: map.getCanvas().clientHeight,
      northY: map.project([center.lng, 85.051129]).y,
      southY: map.project([center.lng, -85.051129]).y,
      worldWidth: map.project([center.lng + 360, center.lat]).x - map.project(center).x,
      renderedFeatures: map.queryRenderedFeatures().length,
    };
  }, { action, longitude, latitude, zoom });
}

export async function expectGeographyFillsCanvas(page: Page) {
  await expect.poll(async () => (await mapCamera(page)).loaded).toBe(true);
  const camera = await mapCamera(page);
  expect(camera.zoom).toBeGreaterThanOrEqual(0);
  expect(camera.northY).toBeLessThanOrEqual(1);
  expect(camera.southY).toBeGreaterThanOrEqual(camera.height - 1);
  expect(camera.renderedFeatures).toBeGreaterThan(0);
  expect(await page.locator('.maplibregl-canvas').evaluate(canvas =>
    canvas.clientWidth === canvas.closest('.map-canvas')!.clientWidth && canvas.clientHeight === canvas.closest('.map-canvas')!.clientHeight)).toBe(true);
}
