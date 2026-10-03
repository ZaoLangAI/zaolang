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

export interface MatrixPage<Cell> {
  /** Values of the axes beyond the first two, e.g. `{ state: 'ruins' }`. */
  presets: Partial<Record<MatrixAxis, string>>;
  /** `rows[r][c]`: the cell at row value r × column value c (null if absent). */
  rows: (Cell | null)[][];
}

export interface MatrixGrid<Cell> {
  rowAxis: MatrixAxis;
  rowValues: string[];
  /** Null when only one axis has values: a single column. */
  colAxis: MatrixAxis | null;
  colValues: string[];
  pageAxes: MatrixAxis[];
  pages: MatrixPage<Cell>[];
}

/**
 * Lays a plan's cells out as §9.3 asks: a table whose rows and columns are
 * the first two axes with picked values, one page per combination of the
 * remaining axes. Cells are matched by their presets; null when nothing is
 * picked.
 */
export function matrixGrid<Cell extends { presets: Partial<Record<string, string | null>> }>(
  axes: Partial<Record<MatrixAxis, readonly string[]>>,
  cells: readonly Cell[],
): MatrixGrid<Cell> | null {
  const used = MATRIX_AXES.filter((axis) => (axes[axis]?.length ?? 0) > 0);
  const [rowAxis, colAxis = null, ...pageAxes] = used;
  if (!rowAxis) return null;
  const values = (axis: MatrixAxis) => [...(axes[axis] ?? [])];
  const key = (presets: Partial<Record<string, string | null>>) =>
    used.map((axis) => presets[axis] ?? '').join('\u0001');
  const byKey = new Map(cells.map((cell) => [key(cell.presets), cell]));

  let pagePresets: Partial<Record<MatrixAxis, string>>[] = [{}];
  for (const axis of pageAxes) {
    pagePresets = pagePresets.flatMap((page) =>
      values(axis).map((value) => ({ ...page, [axis]: value })),
    );
  }
  const colValues = colAxis ? values(colAxis) : [];
  return {
    rowAxis,
    rowValues: values(rowAxis),
    colAxis,
    colValues,
    pageAxes,
    pages: pagePresets.map((presets) => ({
      presets,
      rows: values(rowAxis).map((row) =>
        (colAxis ? colValues : ['']).map(
          (col) =>
            byKey.get(
              key({ ...presets, [rowAxis]: row, ...(colAxis ? { [colAxis]: col } : {}) }),
            ) ?? null,
        ),
      ),
    })),
  };
}
