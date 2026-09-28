import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vitest/config';

const dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
  resolve: {
    alias: {
      '@': path.resolve(dirname, './src'),
      // Next resolves this marker itself (to this same file on the server) and
      // it isn't installed as a package, so server modules would not import here.
      'server-only': path.resolve(dirname, './node_modules/next/dist/compiled/server-only/empty.js'),
    },
  },
});
