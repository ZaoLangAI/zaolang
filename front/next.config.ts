import type { NextConfig } from 'next';
import createNextIntlPlugin from 'next-intl/plugin';

const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: 'standalone',
  env: {
    // Surfaced in the footer to satisfy AGPL section 13.
    NEXT_PUBLIC_SOURCE_URL:
      process.env.SOURCE_REPOSITORY_URL ?? 'https://github.com/ZaoLangAI/zaolang',
    NEXT_PUBLIC_APP_VERSION: process.env.APP_VERSION ?? '0.0.0-dev',
  },
  images: {
    // `search` is deliberately omitted: object keys are matched exactly, and
    // MinIO hands out presigned URLs whose query string differs every time.
    remotePatterns: [
      { protocol: 'http', hostname: 'localhost', port: '9000', pathname: '/**' },
      { protocol: 'http', hostname: '127.0.0.1', port: '9000', pathname: '/**' },
    ],
    // Next 16 refuses to optimise an upstream image that resolves to a private
    // address. That is sound SSRF protection, and it also describes every object
    // served by the local MinIO container — including when the production build
    // is run locally for the Playwright suites, so `NODE_ENV` cannot decide it.
    // A real deployment points at a real object store and leaves this unset.
    dangerouslyAllowLocalIP: process.env.ALLOW_LOCAL_IMAGE_HOSTS === '1',
  },
};

export default withNextIntl(config);
