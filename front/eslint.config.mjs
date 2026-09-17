import coreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';
import prettier from 'eslint-config-prettier';

/**
 * Heavy dependencies that are only supposed to load behind a route or lazy
 * boundary today — see `zaolang-frontend-ui`'s bundle-splitting notes. Each
 * entry's `allow` list is that dependency's one existing, already-isolated
 * home. This exists so a future PR can't reintroduce one into a shared or
 * consumer-facing bundle by a plain, easy-to-miss `import` — it has to
 * deliberately widen this list instead, which is the point.
 */
const heavyDependencyBoundaries = [
  {
    packages: ['@xyflow/react', '@dagrejs/dagre'],
    allow: ['src/components/admin/workflows/**', 'src/components/lineage/**'],
    reason:
      'graph-layout weight belongs only to the admin workflow canvas or the lineage graph (loaded via next/dynamic from LineageDialog) — import it there, not from a route that never renders a graph.',
  },
  {
    packages: ['recharts'],
    allow: ['src/components/admin/**'],
    reason: 'charting only exists in the admin console today — no consumer route renders a chart.',
  },
  {
    packages: ['@mdxeditor/editor'],
    allow: ['src/components/learn/markdown-body-editor-impl.tsx'],
    reason:
      'this file is only ever loaded via next/dynamic({ ssr: false }) from markdown-body-editor.tsx — importing the package anywhere else defeats that split.',
  },
  {
    packages: ['mediabunny'],
    allow: ['src/features/editor/**'],
    reason:
      'export-runner.ts dynamically imports this from inside the cut editor — a static import anywhere else puts WASM weight in a bundle that never needs it.',
  },
  {
    packages: ['animejs'],
    allow: ['src/lib/motion.ts'],
    reason: 'use loadAnime() from lib/motion.ts instead — it already lazy-loads this on demand.',
  },
];

const heavyDependencyBoundaryConfigs = heavyDependencyBoundaries.map(
  ({ packages, allow, reason }) => ({
    files: ['src/**/*.ts', 'src/**/*.tsx'],
    ignores: allow,
    rules: {
      'no-restricted-imports': [
        'error',
        { paths: packages.map((name) => ({ name, message: reason })) },
      ],
    },
  }),
);

const config = [
  {
    ignores: [
      '.next/**',
      'node_modules/**',
      // Generated from the backend contract; formatting it is not our call.
      'src/lib/api/schema.d.ts',
      // Vendored wasm-bindgen output from third_party/opencut-classic — not
      // our source, never hand-edited.
      'public/wasm/opencut/**',
      'playwright-report/**',
      'test-results/**',
    ],
  },
  ...coreWebVitals,
  ...nextTypescript,
  prettier,
  {
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/consistent-type-imports': 'error',
    },
  },
  ...heavyDependencyBoundaryConfigs,
];

export default config;
