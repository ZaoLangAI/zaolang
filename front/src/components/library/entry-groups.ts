import type { AssetEntry, AssetEntryType } from '@/lib/api/types';

export type EntryGroupKey =
  'portrait' | 'sheet' | 'view' | 'expression' | 'detail' | 'master' | 'shot' | 'other';

export interface EntryGroup {
  key: EntryGroupKey;
  /** Approved first, then candidates, each in the card's own order. */
  entries: AssetEntry[];
  candidates: number;
}

const CHARACTER_GROUPS: [EntryGroupKey, AssetEntryType[]][] = [
  ['portrait', ['identity_portrait']],
  ['sheet', ['character_sheet']],
  ['view', ['view']],
  ['expression', ['expression_sheet']],
  ['detail', ['pose', 'outfit_detail', 'prop', 'other']],
];
const SCENE_GROUPS: [EntryGroupKey, AssetEntryType[]][] = [
  ['master', ['master']],
  ['shot', ['shot']],
  ['other', ['other']],
];

/**
 * A look's / variant's images grouped the way the editor shows them
 * (定妆照 / 设定图 / 视角 / 表情 / 细节·其他, or 主图 / 机位 / 其他). Empty
 * groups are dropped. A job's write-back files an image whose slot already
 * holds an approved one as a `candidate` (P2-1), so candidates sit after
 * the approved images of their group, ready to compare and approve.
 */
export function groupEntries(kind: 'character' | 'scene', entries: AssetEntry[]): EntryGroup[] {
  const groups = kind === 'character' ? CHARACTER_GROUPS : SCENE_GROUPS;
  return groups
    .map(([key, types]) => {
      const members = entries.filter((entry) => types.includes(entry.entry_type));
      const approved = members.filter((entry) => entry.status !== 'candidate');
      const candidates = members.filter((entry) => entry.status === 'candidate');
      return { key, entries: [...approved, ...candidates], candidates: candidates.length };
    })
    .filter((group) => group.entries.length > 0);
}

export function candidateCount(entries: AssetEntry[]): number {
  return entries.filter((entry) => entry.status === 'candidate').length;
}
