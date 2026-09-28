#!/usr/bin/env node
/**
 * Verifies every `t('key')` in the source resolves against the zh-CN catalogue.
 *
 * A missing message key is invisible to `tsc` and only surfaces as a runtime
 * error on the page that uses it, which is exactly the kind of defect that
 * survives review. Each call is resolved against the nearest preceding
 * `useTranslations('ns')` / `getTranslations('ns')` call in the same file, so a
 * file using several namespaces is checked per binding.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const messages = JSON.parse(readFileSync(join(root, 'src/i18n/messages/zh-CN.json'), 'utf8'));

function walk(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return walk(full);
    return /\.tsx?$/.test(entry) ? [full] : [];
  });
}

function has(namespace, key) {
  const parts = [...namespace.split('.'), ...key.split('.')];
  let node = messages;
  for (const part of parts) {
    if (typeof node !== 'object' || node === null || !(part in node)) return false;
    node = node[part];
  }
  return typeof node === 'string';
}

const BINDING =
  /(?:const|let)\s+(\w+)\s*=\s*(?:await\s+)?(?:useTranslations|getTranslations)\(\s*'([^']+)'/g;

const missing = [];
for (const file of walk(join(root, 'src'))) {
  const source = readFileSync(file, 'utf8');
  // Several components in one file may each declare `const t = ...` with a
  // different namespace, so keep every binding with its position rather than
  // one namespace per name.
  const bindings = new Map();
  for (const match of source.matchAll(BINDING)) {
    if (!bindings.has(match[1])) bindings.set(match[1], []);
    bindings.get(match[1]).push({ index: match.index, namespace: match[2] });
  }
  if (bindings.size === 0) continue;

  for (const [binding, declarations] of bindings) {
    // Template and computed keys cannot be checked statically; skip them.
    const usage = new RegExp(`\\b${binding}\\(\\s*'([^']+)'`, 'g');
    for (const match of source.matchAll(usage)) {
      // A call belongs to the nearest binding above it; a call above every
      // binding (e.g. a helper hoisted over its component) falls back to the first.
      const namespace = declarations.findLast((d) => d.index < match.index)?.namespace
        ?? declarations[0].namespace;
      if (!has(namespace, match[1])) {
        missing.push(`${file.slice(root.length + 1)}: ${namespace}.${match[1]}`);
      }
    }
  }
}

if (missing.length > 0) {
  console.error(`Missing message keys (${missing.length}):`);
  for (const line of [...new Set(missing)].sort()) console.error(`  ${line}`);
  process.exit(1);
}

console.log('All referenced message keys exist.');
