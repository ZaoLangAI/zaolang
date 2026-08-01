import type { ReactNode } from 'react';

import '@/app/globals.css';

/**
 * The real document shell lives in `[locale]/layout.tsx`, because `<html lang>`
 * and the theme attributes both depend on the request locale. Next still
 * requires a root layout, so this one only passes children through.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return children;
}
