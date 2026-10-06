'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useEffect } from 'react';

import type { Prop } from '@/lib/api/types';
import { propHeroAsset } from '@/lib/props';
import { useResource } from '@/lib/use-resource';

import type { ScriptDocument } from './api';
import { ScriptLinkPicker } from './script-link-picker';

/**
 * The script's props (道具) — found by 拆解建卡, never written by a model
 * turn — each with its linked prop card's hero plate and, on the latest
 * turn, a picker to (re)link it. A segment whose text names a linked prop
 * hands it to video generation (`resolveBreakpointRefs`).
 */
export function ScriptPropsSection({
  document,
  onLink,
  libraryRevision = 0,
}: {
  document: ScriptDocument;
  onLink?: (update: { kind: 'prop'; name: string; refId: string | null }) => void;
  libraryRevision?: number;
}) {
  const t = useTranslations('scriptStudio');
  const props = useResource<Prop[]>(document.props?.length ? '/v1/props' : null);

  useEffect(() => {
    if (libraryRevision) props.refetch();
    // `refetch` is stable; keying on it would only retrigger the same bump.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [libraryRevision]);

  if (!document.props?.length) return null;
  const cards = props.data ?? [];

  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t('props')}</h3>
      <div className="flex flex-wrap gap-2">
        {document.props.map((prop) => {
          const card = cards.find((item) => item.id === prop.prop_ref_id);
          const hero = card ? propHeroAsset(card)?.url : null;
          return (
            <div
              key={prop.name}
              className="flex min-w-0 max-w-full gap-2 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2"
            >
              <div className="relative size-14 shrink-0 overflow-hidden rounded-[var(--radius-sm)] border border-border bg-surface">
                {hero ? (
                  <Image src={hero} alt="" fill sizes="56px" className="object-cover" />
                ) : null}
              </div>
              <div className="flex min-w-0 flex-col gap-1.5">
                <p className="text-sm font-medium">{prop.name}</p>
                {prop.description ? (
                  <p className="max-w-[24ch] text-xs text-muted">{prop.description}</p>
                ) : null}
                {onLink ? (
                  <ScriptLinkPicker
                    kind="prop"
                    refId={prop.prop_ref_id}
                    refreshKey={libraryRevision}
                    onChange={(refId) => onLink({ kind: 'prop', name: prop.name, refId })}
                  />
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
