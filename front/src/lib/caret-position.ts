/**
 * Pixel position of the caret inside a `<textarea>`, relative to the
 * textarea's own top-left corner (its border box).
 *
 * There is no DOM API for this, so the standard trick is used: mirror the
 * textarea's text-affecting styles onto a hidden `<div>`, fill it with the
 * text up to the caret, and read the offset of a marker `<span>` placed
 * right after that text. Scroll position is subtracted at the end because
 * the mirror never scrolls the way the real textarea might.
 *
 * Shared by the script composer's `@` reference menu and the image/video
 * studio prompt field's `@` apply menu.
 */

const MIRRORED_PROPERTIES: (keyof CSSStyleDeclaration)[] = [
  'boxSizing',
  'width',
  'height',
  'overflowX',
  'overflowY',
  'borderTopWidth',
  'borderRightWidth',
  'borderBottomWidth',
  'borderLeftWidth',
  'borderStyle',
  'paddingTop',
  'paddingRight',
  'paddingBottom',
  'paddingLeft',
  'fontStyle',
  'fontVariant',
  'fontWeight',
  'fontStretch',
  'fontSize',
  'fontFamily',
  'lineHeight',
  'textAlign',
  'textTransform',
  'textIndent',
  'textDecoration',
  'letterSpacing',
  'wordSpacing',
  'tabSize',
  'whiteSpace',
  'wordWrap',
];

export interface CaretCoordinates {
  top: number;
  left: number;
  height: number;
}

export function getCaretCoordinates(
  textarea: HTMLTextAreaElement,
  position: number,
): CaretCoordinates {
  const mirror = document.createElement('div');
  const computed = window.getComputedStyle(textarea);

  mirror.style.position = 'absolute';
  mirror.style.visibility = 'hidden';
  mirror.style.top = '0';
  mirror.style.left = '-9999px';
  mirror.style.whiteSpace = 'pre-wrap';
  mirror.style.wordWrap = 'break-word';

  for (const property of MIRRORED_PROPERTIES) {
    const value = computed[property];
    if (typeof value === 'string') {
      // CSSStyleDeclaration keys are camelCase; style.setProperty wants the
      // dashed form, but plain assignment through the same camelCase key
      // works on both the computed and the target style objects.
      (mirror.style as unknown as Record<string, string>)[property as string] = value;
    }
  }

  mirror.textContent = textarea.value.slice(0, position);

  const marker = document.createElement('span');
  // An empty span collapses to zero size in some browsers; a single
  // character keeps its offset meaningful even at the very end of the text.
  marker.textContent = textarea.value.slice(position) || '.';
  mirror.appendChild(marker);

  document.body.appendChild(mirror);
  const top = marker.offsetTop - textarea.scrollTop;
  const left = marker.offsetLeft - textarea.scrollLeft;
  const height = marker.offsetHeight;
  document.body.removeChild(mirror);

  return { top, left, height };
}
