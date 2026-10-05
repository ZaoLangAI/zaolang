import type { ReactNode } from 'react';

export function InspectorSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5 border-t border-border pt-4 first:border-t-0 first:pt-0">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {children}
    </section>
  );
}

/** An `<input type=file>` styled as a secondary button. */
export function UploadButton({
  label,
  title,
  onFile,
}: {
  label: string;
  title?: string;
  onFile: (file: File) => void;
}) {
  return (
    <label
      title={title}
      className="inline-flex cursor-pointer items-center gap-1.5 rounded-[var(--radius-sm)] border border-border px-2.5 py-1.5 text-xs text-muted hover:text-text focus-within:outline-2"
    >
      {label}
      <input
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="sr-only"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFile(file);
          event.target.value = '';
        }}
      />
    </label>
  );
}
