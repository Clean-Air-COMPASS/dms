import { describe, expect, it } from 'vitest';

describe('provider network safety', () => {
  it('contains no executable browser request to the PurpleAir API host', () => {
    const sourceModules = import.meta.glob('../**/*.{ts,tsx}', {
      query: '?raw',
      import: 'default',
      eager: true,
    });
    const forbiddenHost = ['api', 'purpleair', 'com'].join('.');
    const offenders = Object.entries(sourceModules)
      .filter(([path]) => !path.includes('/test/'))
      .filter(([, source]) => String(source).includes(forbiddenHost))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});
