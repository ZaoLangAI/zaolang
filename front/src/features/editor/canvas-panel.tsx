'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';

import { AssetPicker } from './asset-picker';
import type { CanonicalDocument, EditCommand } from './engine/ports';

export function CanvasPanel({
  document,
  disabled,
  onApply,
}: {
  document: CanonicalDocument;
  disabled: boolean;
  onApply: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const [overlayAssetId, setOverlayAssetId] = useState('');

  const isPreset = (width: number, height: number) =>
    document.canvas.width === width && document.canvas.height === height;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant={isPreset(1080, 1920) ? 'primary' : 'secondary'}
          disabled={disabled}
          onClick={() => onApply([{ type: 'set_canvas', width: 1080, height: 1920 }])}
        >
          {t('canvasPresetPortrait')}
        </Button>
        <Button
          size="sm"
          variant={isPreset(1920, 1080) ? 'primary' : 'secondary'}
          disabled={disabled}
          onClick={() => onApply([{ type: 'set_canvas', width: 1920, height: 1080 }])}
        >
          {t('canvasPresetLandscape')}
        </Button>
        <Button
          size="sm"
          variant={isPreset(1080, 1080) ? 'primary' : 'secondary'}
          disabled={disabled}
          onClick={() => onApply([{ type: 'set_canvas', width: 1080, height: 1080 }])}
        >
          {t('canvasPresetSquare')}
        </Button>
      </div>
      <div className="flex flex-col gap-2 border-t border-border pt-3">
        <p className="text-xs text-muted">{t('brandOverlayHint')}</p>
        <div className="flex flex-wrap items-center gap-2">
          <AssetPicker
            value={overlayAssetId || document.brand_overlay?.asset_id}
            mediaType="image"
            disabled={disabled}
            triggerLabel={t('brandOverlayPick')}
            onSelect={(asset) => setOverlayAssetId(asset.id)}
          />
          {overlayAssetId ? (
            <span className="text-xs text-muted">{overlayAssetId}</span>
          ) : null}
          <Button
            size="sm"
            disabled={disabled || !overlayAssetId.trim()}
            onClick={() => {
              onApply([
                {
                  type: 'set_brand_overlay',
                  overlay: {
                    asset_id: overlayAssetId.trim(),
                    x_milli: 40,
                    y_milli: 40,
                    width_milli: 200,
                  },
                },
              ]);
              setOverlayAssetId('');
            }}
          >
            {t('brandOverlayApply')}
          </Button>
        </div>
        {document.brand_overlay ? (
          <Button
            size="sm"
            variant="ghost"
            disabled={disabled}
            onClick={() => onApply([{ type: 'set_brand_overlay', overlay: null }])}
          >
            {t('brandOverlayRemove')}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
