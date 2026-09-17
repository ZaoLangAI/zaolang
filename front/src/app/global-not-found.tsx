import type { Metadata } from 'next';
import Link from 'next/link';

// This bypasses the whole layout tree (that's the point — see
// `next.config.ts`), so it has to bring its own global styles and its own
// `<html>`/`<body>` rather than relying on `[locale]/layout.tsx` for either.
import '@/app/globals.css';

export const metadata: Metadata = {
  title: 'Not Found',
  description: 'The page you are looking for does not exist.',
};

/**
 * Handles requests that never resolve to a `[locale]` segment at all — most
 * commonly a browser's automatic `/favicon.ico` request, or any other path
 * `middleware`/`proxy.ts` didn't rewrite to a locale prefix. Those used to
 * fall through to the passthrough root layout with no `<html>`/`<body>`,
 * which is exactly the warning this file exists to avoid.
 */
export default function GlobalNotFound() {
  return (
    <html lang="zh-CN" data-theme="dark">
      <body className="flex min-h-dvh flex-col items-center justify-center gap-3 bg-bg px-4 text-center text-text antialiased">
        <p className="text-base font-medium">找不到这个页面 · Not Found</p>
        <p className="max-w-md text-sm text-muted">
          链接可能已经失效，或者内容已被作者收回。
          <br />
          The link may be broken, or the content may have been removed.
        </p>
        <Link href="/" className="text-sm font-medium text-primary hover:underline">
          回到首页 · Back home
        </Link>
      </body>
    </html>
  );
}
