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
    packages: ['@xyflow/react'],
    allow: [
      'src/components/admin/workflows/**',
      'src/components/asset-graph/**',
      'src/components/lineage/**',
      'src/features/canvas/**',
    ],
    reason:
      'graph-rendering weight belongs only to the admin workflow canvas, the lineage graph (loaded via next/dynamic from LineageDialog), the card management graph (next/dynamic from asset-graph-workspace) or the studio canvas route — import it there, not from a route that never renders a graph.',
  },
  {
    packages: ['@dagrejs/dagre'],
    allow: [
      'src/components/admin/workflows/**',
      'src/components/asset-graph/**',
      'src/components/lineage/**',
    ],
    reason:
      'graph-layout weight belongs only to the admin workflow canvas or the lineage graph (loaded via next/dynamic from LineageDialog) — import it there, not from a route that never lays out a graph.',
  },
  {
    packages: ['recharts'],
    allow: ['src/components/charts/**'],
    reason:
      'go through the shared TrendChart / BarComparisonChart / ChannelSharePieChart wrappers in components/charts — they bind chart colors to the --color-* tokens.',
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
    packages: ['@photo-sphere-viewer/core'],
    patterns: ['@photo-sphere-viewer/*'],
    allow: ['src/components/media/panorama-viewer.tsx'],
    reason:
      'the panorama viewer pulls in three.js; panorama-viewer.tsx imports it with a dynamic import() inside an effect, so only someone who opens a panorama (canvas director, scene workspace 全景 slot) pays for it — render <PanoramaViewer> instead of importing the package.',
  },
  {
    packages: ['animejs'],
    allow: ['src/lib/motion.ts'],
    reason: 'use loadAnime() from lib/motion.ts instead — it already lazy-loads this on demand.',
  },
];

/**
 * Flat config doesn't merge a rule's options across config objects — a later
 * `no-restricted-imports` replaces an earlier one outright. So instead of one
 * config per boundary, emit exactly one config per region of files: every
 * distinct allow glob is its own region (restricting all packages that glob
 * isn't allowed), and everything outside every allow glob restricts them all.
 */
const heavyDependencySourceFiles = ['src/**/*.ts', 'src/**/*.tsx'];

const restrictHeavyDependencies = (boundaries) => ({
  'no-restricted-imports': [
    'error',
    {
      paths: boundaries.flatMap(({ packages, reason }) =>
        packages.map((name) => ({ name, message: reason })),
      ),
      // Subpath imports (`pkg/index.css`) that `paths`' exact names miss.
      patterns: boundaries
        .filter(({ patterns }) => patterns)
        .map(({ patterns, reason }) => ({ group: patterns, message: reason })),
    },
  ],
});

const heavyDependencyAllowGlobs = [
  ...new Set(heavyDependencyBoundaries.flatMap(({ allow }) => allow)),
];

// Each file must land in at most one region, or the last matching config
// silently wins again. Allow globs are either a `dir/**` or a single file, so
// two regions overlap exactly when one path prefix contains the other.
const allowGlobRoot = (glob) => glob.replace(/\/\*\*$/, '');
for (const a of heavyDependencyAllowGlobs) {
  for (const b of heavyDependencyAllowGlobs) {
    if (a !== b && allowGlobRoot(b).startsWith(`${allowGlobRoot(a)}/`)) {
      throw new Error(`heavyDependencyBoundaries: allow globs ${a} and ${b} overlap`);
    }
  }
}

const heavyDependencyBoundaryConfigs = [
  {
    files: heavyDependencySourceFiles,
    ignores: heavyDependencyAllowGlobs,
    rules: restrictHeavyDependencies(heavyDependencyBoundaries),
  },
  ...heavyDependencyAllowGlobs.map((glob) => ({
    // Nested array = match every pattern, so a `dir/**` glob stays limited to
    // the TS sources above instead of pulling other files into the lint run.
    files: heavyDependencySourceFiles.map((sourceGlob) => [glob, sourceGlob]),
    rules: restrictHeavyDependencies(
      heavyDependencyBoundaries.filter(({ allow }) => !allow.includes(glob)),
    ),
  })),
];

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
