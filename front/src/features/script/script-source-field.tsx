'use client';

import { useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import { IconClose, IconUpload } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import { isApiError } from '@/lib/api/errors';

import { extractScriptSource, type ScriptExtractResult } from './api';

const ACCEPT =
  '.txt,.doc,.docx,.jpg,.jpeg,.png,text/plain,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/jpeg,image/png';
const ALLOWED_EXT = new Set(['txt', 'doc', 'docx', 'jpg', 'jpeg', 'png']);
const MAX_BYTES = 8 * 1024 * 1024;

export function composeScriptIdea(typed: string, extracted: string): string {
  const note = typed.trim();
  const source = extracted.trim();
  if (note && source) return `${note}\n\n${source}`.slice(0, 20_000);
  return (note || source).slice(0, 20_000);
}

function extensionOf(file: File): string {
  const name = file.name.toLowerCase();
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot + 1) : '';
}

export function ScriptSourceField({
  extracted,
  onChange,
  disabled,
}: {
  extracted: ScriptExtractResult | null;
  onChange: (value: ScriptExtractResult | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations('scriptStudio');
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const pick = async (file: File | undefined) => {
    if (!file || disabled) return;
    setError(null);

    if (file.size > MAX_BYTES) {
      setError(t('fileTooLarge'));
      return;
    }
    const ext = extensionOf(file);
    if (!ALLOWED_EXT.has(ext)) {
      setError(t('unsupportedType'));
      return;
    }

    setBusy(true);
    try {
      const result = await extractScriptSource(file);
      onChange(result);
    } catch (caught: unknown) {
      onChange(null);
      setError(isApiError(caught) ? caught.message : t('extractFailed'));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-text">{t('uploadScript')}</label>

      {extracted ? (
        <div className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-surface-soft px-3 py-2">
          <p className="truncate text-sm text-text">
            {t('extractedChip', { filename: extracted.filename, count: extracted.char_count })}
          </p>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              disabled={disabled || busy}
              onClick={() => inputRef.current?.click()}
              className="text-xs text-muted hover:text-text disabled:opacity-60"
            >
              {t('uploadReplace')}
            </button>
            <button
              type="button"
              aria-label={t('uploadRemove')}
              disabled={disabled || busy}
              onClick={() => {
                setError(null);
                onChange(null);
              }}
              className="grid size-7 place-items-center rounded-full text-muted hover:text-danger disabled:opacity-60"
            >
              <IconClose className="size-4" />
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          disabled={disabled || busy}
          onClick={() => inputRef.current?.click()}
          onDragOver={(event) => {
            event.preventDefault();
            if (!disabled && !busy) setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragOver(false);
            void pick(event.dataTransfer.files?.[0]);
          }}
          className={`flex min-h-24 w-full flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed text-sm transition-colors disabled:opacity-60 ${
            dragOver
              ? 'border-border-strong bg-surface-soft text-text'
              : 'border-border text-muted hover:border-border-strong hover:text-text'
          }`}
        >
          {busy ? <Spinner label={t('extracting')} /> : <IconUpload className="size-6" />}
          {!busy ? t('uploadScriptCta') : null}
        </button>
      )}

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        aria-label={t('uploadScript')}
        className="sr-only"
        disabled={disabled || busy}
        onChange={(event) => void pick(event.target.files?.[0])}
      />

      <p className="text-xs leading-relaxed text-muted">{t('uploadScriptHint')}</p>
      {extracted?.truncated ? (
        <p className="text-xs text-muted">{t('extractedTruncated')}</p>
      ) : null}
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
