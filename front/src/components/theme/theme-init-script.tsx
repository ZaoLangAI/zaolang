'use client';

import { useServerInsertedHTML } from 'next/navigation';
import { useRef } from 'react';

import { themeInitScript } from '@/lib/theme';

/**
 * Injects `themeInitScript` into `<head>` via the SSR HTML stream.
 *
 * A `<script>` rendered as a React child would hit React 19's client-side
 * "Encountered a script tag" error. `useServerInsertedHTML` writes the same
 * blocking snippet into the document head without putting it in the hydrating
 * tree, so `system` still resolves before first paint.
 */
export function ThemeInitScript() {
  const inserted = useRef(false);

  useServerInsertedHTML(() => {
    if (inserted.current) return null;
    inserted.current = true;
    return <script id="zl-theme-init" dangerouslySetInnerHTML={{ __html: themeInitScript }} />;
  });

  return null;
}
