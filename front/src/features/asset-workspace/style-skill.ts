/**
 * The plaza's 用于角色 / 场景 / 道具创作 (AC-8) lands on a library with
 * `?skillId=`; every card link there keeps it, and the card workspace's 创作
 * slot panel preselects it as the style skill. Kept out of client modules
 * so the route pages (server components) can parse it.
 */

/** `CreationSkill.id` is `sk_` + a Crockford token in a `String(40)` column;
 * anything else is dropped so a crafted value never reaches `/v1/skills/{id}`. */
export function parseStyleSkillId(raw: string | undefined | null): string | null {
  if (!raw || raw.length > 40 || !/^sk_[0-9A-Za-z]+$/.test(raw)) return null;
  return raw;
}

/** `href` with the carried style skill appended (no-op without one). */
export function withStyleSkill(href: string, skillId?: string | null): string {
  if (!skillId) return href;
  const hashAt = href.indexOf('#');
  const path = hashAt < 0 ? href : href.slice(0, hashAt);
  const hash = hashAt < 0 ? '' : href.slice(hashAt);
  const separator = path.includes('?') ? '&' : '?';
  return `${path}${separator}skillId=${encodeURIComponent(skillId)}${hash}`;
}
