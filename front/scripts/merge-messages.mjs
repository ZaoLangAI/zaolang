#!/usr/bin/env node
/**
 * Merges a namespace fragment into all three message catalogues at once.
 *
 * Hand-editing three files invites drift, and drift only shows up as a missing
 * string in a language nobody on the team reads. Usage:
 *
 *   node scripts/merge-messages.mjs fragment.json
 *
 * where the fragment is `{ "zh-CN": {...}, "en": {...}, "ja": {...} }`.
 *
 * A locale may be omitted. It then falls back to `en`, which is how the console
 * strings ship: they are written in Chinese and English, and Japanese readers
 * see English rather than an untranslated key.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const messagesDir = resolve(here, '../src/i18n/messages');

const fragmentPath = process.argv[2];
if (!fragmentPath) {
  console.error('usage: merge-messages.mjs <fragment.json>');
  process.exit(1);
}

const fragment = JSON.parse(readFileSync(fragmentPath, 'utf8'));

function deepMerge(target, source) {
  for (const [key, value] of Object.entries(source)) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      target[key] = deepMerge(target[key] ?? {}, value);
    } else {
      target[key] = value;
    }
  }
  return target;
}

for (const locale of ['zh-CN', 'en', 'ja']) {
  const file = resolve(messagesDir, `${locale}.json`);
  const current = JSON.parse(readFileSync(file, 'utf8'));
  const addition = fragment[locale] ?? fragment.en ?? {};
  const merged = deepMerge(current, addition);
  const sorted = Object.fromEntries(Object.entries(merged).sort(([a], [b]) => a.localeCompare(b)));
  writeFileSync(file, `${JSON.stringify(sorted, null, 2)}\n`, 'utf8');
  console.log(`merged into ${locale}`);
}
