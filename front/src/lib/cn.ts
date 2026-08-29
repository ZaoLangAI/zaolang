/** Joins class names, dropping falsy entries. */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}

/**
 * Shared press/hover affordance for consumer controls that are not `Button`.
 * Transitions collapse under reduced-motion via `globals.css`.
 */
export const controlPress =
  'transition-[color,background-color,border-color,transform,filter] active:scale-[0.98] active:brightness-[0.96] disabled:active:scale-100';
