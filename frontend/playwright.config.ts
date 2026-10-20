import { defineConfig, devices } from '@playwright/test';
import { validatePlaywrightTarget } from './e2e/isolated-qa-preflight';

const target = validatePlaywrightTarget();

export default defineConfig({
  testDir: './e2e',
  outputDir: target.outputDir,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [
    ['list'],
    ['json', { outputFile: `${target.outputDir}/playwright-report.json` }],
  ],
  use: {
    baseURL: target.baseUrl,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
});
