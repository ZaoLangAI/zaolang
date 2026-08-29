/**
 * Resolves a keyframed property to its effective value at a given tick.
 * Mirrors OpenCut's documented resolver shape (`docs/keyframes.md`'s
 * `resolveNumberAtTime`) as a design reference, not shared code — their
 * channels live in a local store mutated directly; ours only ever change
 * through `set_keyframe`/`delete_keyframe`/`clear_keyframes` under CAS.
 */

import type { AnimatableProperty, AnimationPoint, ElementAnimations, EasingType } from './ports';

/**
 * Reshapes a 0-1 interpolation ratio per the *departing* point's `easing` —
 * i.e. the curve used leaving that point towards the next one. Missing
 * (`undefined`) or unrecognized values fall through to `'linear'`, which
 * covers every point persisted before this field existed (invariant: no
 * SCHEMA_VERSION migration, read-time default instead).
 */
function applyEasing(ratio: number, easing: EasingType | undefined): number {
  switch (easing) {
    case 'ease_in':
      return ratio * ratio;
    case 'ease_out':
      return 1 - (1 - ratio) * (1 - ratio);
    default:
      return ratio;
  }
}

/**
 * Interpolation (linear by default, reshaped by the departing point's
 * `easing`) between the two points bracketing `atTicks`; holds the nearest
 * edge point's value outside the keyframed range; falls back to `baseValue`
 * when the property has no channel (or an empty one) at all.
 */
export function resolveNumberAtTime(
  animations: ElementAnimations | undefined,
  property: AnimatableProperty,
  atTicks: number,
  baseValue: number,
): number {
  const points = animations?.channels[property]?.points;
  if (!points || points.length === 0) return baseValue;
  if (points.length === 1) return points[0]!.value;

  const sorted = [...points].sort((a, b) => a.at_ticks - b.at_ticks);
  const first = sorted[0]!;
  const last = sorted[sorted.length - 1]!;
  if (atTicks <= first.at_ticks) return first.value;
  if (atTicks >= last.at_ticks) return last.value;

  for (let index = 0; index < sorted.length - 1; index += 1) {
    const left = sorted[index]!;
    const right = sorted[index + 1]!;
    if (atTicks >= left.at_ticks && atTicks <= right.at_ticks) {
      if (right.at_ticks === left.at_ticks) return right.value;
      const ratio = (atTicks - left.at_ticks) / (right.at_ticks - left.at_ticks);
      const eased = applyEasing(ratio, left.easing);
      return left.value + (right.value - left.value) * eased;
    }
  }
  return last.value;
}

export function pointsFor(
  animations: ElementAnimations | undefined,
  property: AnimatableProperty,
): AnimationPoint[] {
  return animations?.channels[property]?.points ?? [];
}
