/**
 * Same quoting/Blob-download idiom as the admin log center's inline CSV
 * export (`log-center-console.tsx`) — kept local to this feature rather than
 * promoted to a shared helper, since generalizing three call sites across
 * unrelated features isn't this change's job.
 */
export function downloadCsv(
  filename: string,
  headers: string[],
  rows: (string | number)[][],
): void {
  const csv = [headers, ...rows]
    .map((cells) => cells.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(','))
    .join('\n');

  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
