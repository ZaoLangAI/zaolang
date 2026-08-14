'use client';

import { useEffect, useState, type RefObject } from 'react';

import { REFERENCE_CANVAS } from '@/lib/devices';

/**
 * Width of `node` plus the remaining viewport below its top, capped at the
 * iPhone 17 canvas (and an optional extra ceiling). Using remaining viewport
 * — not the node's own height — avoids a loop where the child sizes the
 * parent that then sizes the child.
 */
export function useAvailableStage(
  nodeRef: RefObject<HTMLElement | null>,
  maxHeight?: number,
): { width: number; height: number } {
  const [box, setBox] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const node = nodeRef.current;
    if (!node) return;

    const update = () => {
      const rect = node.getBoundingClientRect();
      const remaining = Math.max(0, window.innerHeight - rect.top - 16);
      const canvasCap = REFERENCE_CANVAS.height;
      const height = Math.min(
        canvasCap,
        maxHeight && maxHeight > 0 ? maxHeight : canvasCap,
        remaining || canvasCap,
      );
      setBox({ width: rect.width, height });
    };

    const observer = new ResizeObserver(update);
    observer.observe(node);
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    update();
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [maxHeight, nodeRef]);

  return box;
}
