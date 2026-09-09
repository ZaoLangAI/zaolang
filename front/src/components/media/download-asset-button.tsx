'use client';

import { useState } from 'react';

import { Button, type ButtonProps } from '@/components/ui/button';
import { IconDownload } from '@/components/ui/icons';
import { useToast } from '@/components/ui/toast';
import { isApiError } from '@/lib/api/errors';
import { downloadAsset } from '@/lib/download-asset';

export function DownloadAssetButton({
  assetId,
  label,
  failedMessage,
  variant = 'secondary',
  size = 'sm',
  className,
}: {
  assetId: string;
  label: string;
  failedMessage: string;
  variant?: ButtonProps['variant'];
  size?: ButtonProps['size'];
  className?: string;
}) {
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      await downloadAsset(assetId);
    } catch (error) {
      notify(isApiError(error) ? error.message : failedMessage, 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button
      variant={variant}
      size={size}
      className={className}
      icon={<IconDownload className={size === 'lg' ? 'size-5' : 'size-4'} />}
      loading={busy}
      onClick={() => void run()}
    >
      {label}
    </Button>
  );
}
