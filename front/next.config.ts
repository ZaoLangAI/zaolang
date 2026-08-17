import type { NextConfig } from 'next';
import createNextIntlPlugin from 'next-intl/plugin';

const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');
const localMediaHost = process.env.LOCAL_MEDIA_HOST?.trim();
const allowedDevOrigins = (process.env.NEXT_ALLOWED_DEV_ORIGINS ?? '')
  .split(',')
  .map((origin) => origin.trim())
  .filter(Boolean);

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: 'standalone',
  allowedDevOrigins,
  env: {
    NEXT_PUBLIC_APP_VERSION: process.env.APP_VERSION ?? '0.0.0-dev',
  },
  images: {
    // `search` is deliberately omitted: object keys are matched exactly, and
    // MinIO hands out presigned URLs whose query string differs every time.
    remotePatterns: [
      { protocol: 'http', hostname: 'localhost', port: '9000', pathname: '/**' },
      { protocol: 'http', hostname: '127.0.0.1', port: '9000', pathname: '/**' },
      // LOCAL_MEDIA_HOST is an escape hatch, not for DHCP-assigned NIC IPs —
      // those change and then signed URLs plus this allowlist both break.
      ...(localMediaHost
        ? [{ protocol: 'http' as const, hostname: localMediaHost, port: '9000', pathname: '/**' }]
        : []),
    ],
    // Next 16 refuses to optimise an upstream image that resolves to a private
    // address. That is sound SSRF protection, and it also describes every object
    // served by the local MinIO container — including when the production build
    // is run locally for the Playwright suites, so `NODE_ENV` cannot decide it.
    // A real deployment points at a real object store and leaves this unset.
    dangerouslyAllowLocalIP: process.env.ALLOW_LOCAL_IMAGE_HOSTS === '1',
    // A single-host deployment with no domain signs media URLs with the
    // server's bare public IP. Optimising those would make the Next server
    // fetch that same public IP from inside its own container — whether that
    // loops back depends on the host's NAT and isn't something to rely on.
    // Skipping optimisation also bypasses the `remotePatterns` allow-list, so
    // the browser fetches the signed URL directly instead.
    unoptimized: process.env.NEXT_IMAGES_UNOPTIMIZED === '1',
  },
};

export default withNextIntl(config);
