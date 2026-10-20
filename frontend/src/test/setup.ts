import '@testing-library/jest-dom';
import { vi } from 'vitest';
import '../i18n';


vi.mock('../mapWebGlSupport', () => ({ isMapWebGl2Available: () => true }));

vi.mock('maplibre-gl', () => ({
  setWorkerUrl: vi.fn(),
  Map: vi.fn(function MockMap() {
    const map = {
      on: vi.fn((eventName: string, callback: () => void) => {
        if (eventName === 'load') queueMicrotask(callback);
        return map;
      }),
      remove: vi.fn(), addControl: vi.fn(), setPadding: vi.fn(), flyTo: vi.fn(),
      fitBounds: vi.fn(), resize: vi.fn(), jumpTo: vi.fn(), easeTo: vi.fn(),
      project: vi.fn(() => ({ x: 0, y: 0 })),
      unproject: vi.fn(() => ({ lng: 0, lat: 0 })),
      getBounds: vi.fn(() => ({ getWest: () => -10, getSouth: () => 40, getEast: () => 10, getNorth: () => 55 })),
      getSource: vi.fn(), addSource: vi.fn(), addLayer: vi.fn(), getLayer: vi.fn(),
      removeLayer: vi.fn(), removeSource: vi.fn(),
    };
    return map;
  }),
  Marker: vi.fn(function MockMarker(options?: { element?: HTMLElement }) {
    const element = options?.element || document.createElement('div');
    const marker = {
      setLngLat: vi.fn(() => marker),
      addTo: vi.fn(() => {
        document.body.appendChild(element);
        return marker;
      }),
      remove: vi.fn(() => element.remove()),
      getElement: vi.fn(() => element),
    };
    return marker;
  }),
  NavigationControl: vi.fn(function MockNavigationControl() {}),
  LngLat: vi.fn(function MockLngLat(lng: number, lat: number) { return { lng, lat }; }),
  LngLatBounds: vi.fn(function MockLngLatBounds() { return {
    extend: vi.fn().mockReturnThis(),
  }; }),
}));


vi.mock('react-chartjs-2', () => ({
  Line: () => null,
}));


(globalThis as Record<string, unknown>).ResizeObserver = vi.fn().mockImplementation(function MockResizeObserver() { return {
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}; });
