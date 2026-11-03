import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  testMatch: /.*\.spec\.ts/,
  timeout: 30_000,
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: "http://127.0.0.1:3100" },
  webServer: {
    // PLAYWRIGHT=1 enables the __mock fixtures inside the data layer.
    // Requires a prior `npm run build`.
    command: "PLAYWRIGHT=1 npx next start -p 3100",
    url: "http://127.0.0.1:3100/slate",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
