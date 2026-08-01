'use client';

import { forwardRef } from 'react';

import { Spinner } from '@/components/ui/spinner';
import { cn } from '@/lib/cn';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'link';
type Size = 'sm' | 'md' | 'lg';

const variants: Record<Variant, string> = {
  primary:
    'bg-primary text-on-primary hover:bg-primary-hover disabled:bg-primary/40 disabled:text-on-primary/70',
  secondary:
    'bg-surface-soft text-text border border-border hover:bg-surface-raised hover:border-muted/40',
  ghost: 'text-muted hover:text-text hover:bg-surface-soft',
  danger: 'bg-danger text-white hover:brightness-110',
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
        'inline-flex select-none items-center justify-center font-medium transition-colors',
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
