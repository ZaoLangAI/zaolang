#!/usr/bin/env node
/**
 * Fails when the built JS bundle grows past the committed budget in
 * `bundle-budget.json`.
 *
 * Two numbers matter for different reasons: the shared root bundle
 * (`build-manifest.json`'s `rootMainFiles`) is what every single page pays
 * for on its first load, so it is the one that most directly costs first-load
 * speed; the total across `.next/static/chunks` is a coarser trip-wire for
 * "something heavy got pulled in somewhere" even if it landed in a route-level
 * chunk rather than the shared one. Neither number can shrink on its own —
 * this only catches growth, and only once someone runs a production build.
 *
 * Must run after `next build` (see `make test-front`), against `front/.next`.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const here = dirname(fileURLToPath(import.meta.url));
const frontDir = resolve(here, '..');
const nextDir = join(frontDir, '.next');
const budget = JSON.parse(readFileSync(join(here, 'bundle-budget.json'), 'utf8'));

function readManifest() {
  try {
    return JSON.parse(readFileSync(join(nextDir, 'build-manifest.json'), 'utf8'));
  } catch {
    console.error(
      'Could not read .next/build-manifest.json — run `next build` before check:bundle-size ' +
        '(see `make test-front`, which already does both in order).',
    );
    process.exit(1);
  }
}

function walkJsFiles(dir) {
  let files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) files = files.concat(walkJsFiles(full));
    else if (entry.name.endsWith('.js')) files.push(full);
  }
  return files;
}

function sizeReport(paths) {
  let raw = 0;
  let gzip = 0;
  for (const path of paths) {
    const buf = readFileSync(path);
    raw += buf.length;
    gzip += gzipSync(buf).length;
  }
  return { raw, gzip };
}

const kb = (bytes) => bytes / 1024;

const manifest = readManifest();
const rootFiles = (manifest.rootMainFiles ?? [])
  .filter((f) => f.endsWith('.js'))
  .map((f) => join(nextDir, f));
if (rootFiles.length === 0) {
  console.error(
    'build-manifest.json has no rootMainFiles — its shape changed and this script needs updating.',
  );
  process.exit(1);
}

const chunksDir = join(nextDir, 'static', 'chunks');
let totalFiles;
try {
  totalFiles = walkJsFiles(chunksDir);
} catch {
  console.error(`Could not read ${chunksDir} — run \`next build\` first.`);
  process.exit(1);
}

const root = sizeReport(rootFiles);
const total = sizeReport(totalFiles);

const checks = [
  {
    label: 'shared root JS (every page pays this)',
    measured: root,
    rawBudget: budget.rootRawKb,
    gzipBudget: budget.rootGzipKb,
  },
  {
    label: 'whole app JS (.next/static/chunks)',
    measured: total,
    rawBudget: budget.totalRawKb,
    gzipBudget: budget.totalGzipKb,
  },
];

let failed = false;
for (const check of checks) {
  const rawKb = kb(check.measured.raw);
  const gzipKb = kb(check.measured.gzip);
  const rawOver = rawKb > check.rawBudget;
  const gzipOver = gzipKb > check.gzipBudget;
  const status = rawOver || gzipOver ? 'FAIL' : 'ok';
  console.log(
    `[${status}] ${check.label}: ${rawKb.toFixed(1)}KB raw (budget ${check.rawBudget}KB), ` +
      `${gzipKb.toFixed(1)}KB gzip (budget ${check.gzipBudget}KB)`,
  );
  if (rawOver || gzipOver) failed = true;
}

if (failed) {
  console.error(
    '\nBundle size exceeds the committed budget in scripts/bundle-budget.json. If this growth is a ' +
      'deliberate, understood tradeoff (a new dependency, a bigger shared provider), bump the relevant ' +
      'number there with a short reason in the commit message. If not, find what pulled the extra ' +
      'weight in — e.g. a heavy dependency imported outside its usual lazy-loaded boundary — and fix that ' +
      'instead of the budget.',
  );
  process.exit(1);
}

console.log('bundle size within budget');
