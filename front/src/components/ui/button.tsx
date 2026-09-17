'use client';

import { forwardRef } from 'react';

import { Spinner } from '@/components/ui/spinner';
import { cn, controlPress } from '@/lib/cn';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'link';
type Size = 'sm' | 'md' | 'lg';

const variants: Record<Variant, string> = {
  primary:
    'bg-primary text-on-primary hover:bg-primary-hover disabled:bg-primary/40 disabled:text-on-primary/70',
  secondary:
    'bg-surface-soft text-text border border-border hover:bg-surface-raised hover:border-muted/40',
  ghost: 'text-muted hover:text-text hover:bg-surface-soft',
  danger: 'bg-danger text-on-danger hover:brightness-110',
  link: 'text-primary underline-offset-4 hover:underline px-0',
};

const sizes: Record<Size, string> = {
  // 44px minimum touch target on every size the design uses for real controls.
  sm: 'h-9 px-3 text-sm gap-1.5 rounded-[var(--radius-sm)]',
  md: 'h-11 px-4 text-sm gap-2 rounded-[var(--radius-sm)]',
  lg: 'h-13 px-6 text-base gap-2.5 rounded-[var(--radius-md)]',
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  /** Rendered before the label; decorative, so it is hidden from the tree. */
  icon?: React.ReactNode;
  fullWidth?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'primary',
    size = 'md',
    loading = false,
    icon,
    fullWidth,
    className,
    children,
    disabled,
    type = 'button',
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      // A loading button stays focusable but refuses activation, so focus is
      // not thrown back to the document body mid-interaction.
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      className={cn(
        'inline-flex select-none items-center justify-center font-medium',
        controlPress,
        'disabled:cursor-not-allowed disabled:opacity-70',
        variants[variant],
        sizes[size],
        fullWidth && 'w-full',
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Spinner />
      ) : icon ? (
        <span aria-hidden="true" className="inline-flex shrink-0">
          {icon}
        </span>
      ) : null}
      {children}
    </button>
  );
});

const iconButtonSizes: Record<Size, string> = {
  sm: 'size-9 rounded-[var(--radius-sm)]',
  md: 'size-11 rounded-[var(--radius-sm)]',
  lg: 'size-13 rounded-[var(--radius-md)]',
};

export interface IconButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  /** No visible text sits next to the icon, so this doubles as the
   * accessible name and the hover tooltip. */
  label: string;
  children: React.ReactNode;
}

/**
 * A square, icon-only button: a dense action row (e.g. an agent card's
 * edit/debug/delete row) that would otherwise wrap across lines once every
 * action carries its own text label.
 *
 * Kept separate from {@link Button} rather than an `iconOnly` flag on it —
 * that component's padding and gap are tuned for icon-plus-text, which does
 * not collapse cleanly to a centered square.
 */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { variant = 'ghost', size = 'sm', loading = false, label, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      className={cn(
        'inline-flex shrink-0 select-none items-center justify-center',
        controlPress,
        'disabled:cursor-not-allowed disabled:opacity-70',
        variants[variant],
        iconButtonSizes[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Spinner /> : <span aria-hidden="true">{children}</span>}
    </button>
  );
});
