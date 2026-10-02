import { readFileSync } from 'node:fs';

/**
 * Ids of the rows `make e2e-fixtures` plants (`back/app/scripts/e2e_fixtures.py`).
 *
 * `make seed` loads only accounts and system defaults, so the published works,
 * the paid skill, the draft and the failed job these specs walk come from that
 * separate script. It writes this manifest; `make test-e2e` and `make qa-visual`
 * run it first. Titles live here too so a spec and the script cannot drift
 * apart silently — renaming one breaks the other loudly.
 */
export interface E2eFixtures {
  free_remix_work_id: string;
  withdrawn_work_id: string;
  paid_work_id: string;
  paid_skill_id: string;
  draft_id: string;
  failed_job_id: string;
}

export const FIXTURE_TITLES = {
  /** Active free remix in the chain; its parent's child was withdrawn. */
  freeRemix: '潮汐之上 · 夜行',
  withdrawn: 'Night Tide (withdrawn)',
  /** The remix of the withdrawn work — still public, so the chain resolves. */
  deepRemix: 'Night Tide · Neon',
  paidWork: '潮汐之上 · 付费样例',
  paidSkill: '黄金时刻镜头',
  draft: '潮汐之上 · 未完成',
} as const;

const MANIFEST = 'e2e/.fixtures.json';

let cached: E2eFixtures | null = null;

export function fixtures(): E2eFixtures {
  if (cached) return cached;
  let raw: string;
  try {
    raw = readFileSync(MANIFEST, 'utf-8');
  } catch {
    throw new Error(
      `${MANIFEST} is missing — run \`make e2e-fixtures\` (after \`make seed\`) before these specs.`,
    );
  }
  cached = JSON.parse(raw) as E2eFixtures;
  return cached;
}
