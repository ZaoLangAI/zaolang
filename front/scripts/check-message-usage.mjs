#!/usr/bin/env node
/**
 * Verifies every `t('key')` in the source resolves against the zh-CN catalogue.
 *
 * A missing message key is invisible to `tsc` and only surfaces as a runtime
 * error on the page that uses it, which is exactly the kind of defect that
 * survives review. Namespaces are read from the nearest
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
  const namespaces = new Map();
  for (const match of source.matchAll(BINDING)) namespaces.set(match[1], match[2]);
  if (namespaces.size === 0) continue;

  for (const [binding, namespace] of namespaces) {
    // Template and computed keys cannot be checked statically; skip them.
    const usage = new RegExp(`\\b${binding}\\(\\s*'([^']+)'`, 'g');
    for (const match of source.matchAll(usage)) {
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
