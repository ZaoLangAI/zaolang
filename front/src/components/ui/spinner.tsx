import { cn } from '@/lib/cn';

/**
 * Motion-reduced users get a pulsing dot instead of a spin; the CSS override in
 * `globals.css` freezes the rotation, which would otherwise look broken.
 */
export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span
      className={cn('inline-flex items-center gap-2', className)}
      role="status"
      aria-live="polite"
    >
      <svg
        className="size-4 animate-spin motion-reduce:animate-pulse"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <circle
          cx="12"
          cy="12"
          r="9"
          stroke="currentColor"
          strokeOpacity="0.25"
          strokeWidth="2.5"
        />
        <path
          d="M21 12a9 9 0 0 0-9-9"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
      {label ? <span className="text-sm">{label}</span> : null}
    </span>
  );
}
