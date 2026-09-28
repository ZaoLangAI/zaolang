import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Dialog } from './dialog';

const motion = vi.hoisted(() => ({ reduced: false }));

vi.mock('@/lib/motion', async () => {
  const { useLayoutEffect } = await import('react');
  return {
    useIsomorphicLayoutEffect: useLayoutEffect,
    useReducedMotion: () => motion.reduced,
    loadAnime: () => Promise.resolve({ animate: () => Promise.resolve() }),
  };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let autoFocusField = false;

function Harness({ open }: { open: boolean }) {
  return (
    <>
      <button type="button" data-testid="trigger">
        open
      </button>
      <Dialog open={open} onClose={() => {}} title="Gallery">
        {autoFocusField ? <input data-testid="field" autoFocus /> : null}
      </Dialog>
    </>
  );
}

const trigger = () => document.querySelector<HTMLElement>('[data-testid="trigger"]')!;
const panel = () => document.querySelector<HTMLElement>('[role="dialog"]');

function setOpen(open: boolean) {
  root.render(<Harness open={open} />);
}

async function toggle(open: boolean) {
  await act(async () => setOpen(open));
}

describe.each([false, true])('Dialog focus (reduced motion: %s)', (reduced) => {
  beforeEach(() => {
    motion.reduced = reduced;
    autoFocusField = false;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.style.overflow = '';
  });

  it('focuses the mounted panel on open and returns focus to the opener on close', async () => {
    act(() => setOpen(false));
    trigger().focus();

    await toggle(true);
    expect(document.activeElement).toBe(panel());
    expect(document.body.style.overflow).toBe('hidden');

    await toggle(false);
    expect(document.activeElement).toBe(trigger());
    expect(document.body.style.overflow).toBe('');
  });

  it('survives a rapid close and reopen', async () => {
    act(() => setOpen(false));
    trigger().focus();

    await toggle(true);
    const first = panel();
    // Synchronous `act`s: the exit animation's promise has not settled yet,
    // so the reopen lands mid-exit with the panel still mounted.
    act(() => setOpen(false));
    act(() => setOpen(true));
    if (!reduced) expect(panel()).toBe(first);
    expect(document.activeElement).toBe(panel());
    expect(document.body.style.overflow).toBe('hidden');

    await toggle(false);
    expect(document.activeElement).toBe(trigger());
    expect(document.body.style.overflow).toBe('');
  });

  it('leaves an autoFocus field focused and still restores the opener', async () => {
    autoFocusField = true;
    act(() => setOpen(false));
    trigger().focus();

    await toggle(true);
    expect(document.activeElement).toBe(document.querySelector('[data-testid="field"]'));

    await toggle(false);
    expect(document.activeElement).toBe(trigger());
  });
});
