/** Server-side limits (`app.domain.scenes.matrix`). */
export const MAX_MATRIX_CELLS = 12;
export const MAX_MATRIX_AXIS_VALUES = 4;

export const MATRIX_AXES = ['lighting', 'weather', 'state', 'period'] as const;
export type MatrixAxis = (typeof MATRIX_AXES)[number];

/**
 * How many cells the picked values make — the cartesian product over the
 * axes that have at least one value (0 when none has). Mirrors the backend
 * so the dialog can say "too many" before asking the server.
 */
export function matrixCellCount(axes: Partial<Record<MatrixAxis, readonly string[]>>): number {
  const sizes = MATRIX_AXES.map((axis) => axes[axis]?.length ?? 0).filter((n) => n > 0);
  return sizes.length ? sizes.reduce((product, n) => product * n, 1) : 0;
}
