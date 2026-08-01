#!/usr/bin/env node
/**
 * Fails when the three catalogues do not describe exactly the same keys.
 *
 * A missing key renders as the raw key path in production, and nobody notices
 * until a reader of that language complains. This turns it into a build error.
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const messagesDir = resolve(here, '../src/i18n/messages');
const locales = ['zh-CN', 'en', 'ja'];

function flatten(value, prefix = '') {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return Object.entries(value).flatMap(([key, child]) =>
      flatten(child, prefix ? `${prefix}.${key}` : key),
    );
  }
  return [prefix];
}

const keysByLocale = new Map(
  locales.map((locale) => [
    locale,
    new Set(flatten(JSON.parse(readFileSync(resolve(messagesDir, `${locale}.json`), 'utf8')))),
  ]),
);

const reference = keysByLocale.get(locales[0]);
let failed = false;

for (const locale of locales.slice(1)) {
  const keys = keysByLocale.get(locale);
  const missing = [...reference].filter((key) => !keys.has(key));
  const extra = [...keys].filter((key) => !reference.has(key));

  if (missing.length) {
    failed = true;
    console.error(`${locale} is missing ${missing.length} key(s):\n  ${missing.join('\n  ')}`);
  }
  if (extra.length) {
    failed = true;
    console.error(`${locale} has ${extra.length} unexpected key(s):\n  ${extra.join('\n  ')}`);
  }
}

if (failed) process.exit(1);
console.log(`all ${locales.length} catalogues agree on ${reference.size} keys`);
