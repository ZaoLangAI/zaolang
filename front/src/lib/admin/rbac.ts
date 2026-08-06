/**
 * Console roles, ordered.
 *
 * The server enforces these; the client uses them only to hide navigation the
 * operator cannot use. Trimming the menu is a courtesy, never a control — every
 * hidden route still returns 403 if requested directly.
 */
export const ADMIN_ROLES = ['viewer', 'reviewer', 'operator', 'admin'] as const;
export type AdminRole = (typeof ADMIN_ROLES)[number];

const RANK: Record<AdminRole, number> = { viewer: 1, reviewer: 2, operator: 3, admin: 4 };

export function isAdminRole(value: string): value is AdminRole {
  return (ADMIN_ROLES as readonly string[]).includes(value);
}

export function highestRole(roles: string[]): AdminRole {
  return roles
    .filter(isAdminRole)
    .reduce<AdminRole>((best, role) => (RANK[role] > RANK[best] ? role : best), 'viewer');
}

export function atLeast(role: AdminRole, required: AdminRole): boolean {
  return RANK[role] >= RANK[required];
}

export interface NavItem {
  href: string;
  labelKey: string;
  requires: AdminRole;
  icon:
    | 'health'
    | 'jobs'
    | 'providers'
    | 'routing'
    | 'agents'
    | 'moderation'
    | 'reports'
    | 'learnPosts'
    | 'skillLibrary'
    | 'users'
    | 'credits'
    | 'config'
    | 'data'
    | 'audit'
    | 'announcements';
}

export interface NavGroup {
  labelKey: string;
  items: NavItem[];
}

/** Grouped by the ten operational domains from the plan, in reading order. */
export const NAV_GROUPS: NavGroup[] = [
  {
    labelKey: 'groupRuntime',
    items: [
      { href: '/admin', labelKey: 'navHealth', requires: 'viewer', icon: 'health' },
      { href: '/admin/jobs', labelKey: 'navJobs', requires: 'viewer', icon: 'jobs' },
      { href: '/admin/providers', labelKey: 'navProviders', requires: 'viewer', icon: 'providers' },
      { href: '/admin/routing', labelKey: 'navRouting', requires: 'viewer', icon: 'routing' },
      { href: '/admin/agents', labelKey: 'navAgents', requires: 'viewer', icon: 'agents' },
    ],
  },
  {
    labelKey: 'groupDomain',
    items: [
      {
        href: '/admin/moderation',
        labelKey: 'navModeration',
        requires: 'reviewer',
        icon: 'moderation',
      },
      { href: '/admin/reports', labelKey: 'navReports', requires: 'reviewer', icon: 'reports' },
      {
        href: '/admin/learn-posts',
        labelKey: 'navLearnPosts',
        requires: 'reviewer',
        icon: 'learnPosts',
      },
      {
        href: '/admin/skill-library',
        labelKey: 'navSkillLibrary',
        requires: 'reviewer',
        icon: 'skillLibrary',
      },
      { href: '/admin/users', labelKey: 'navUsers', requires: 'reviewer', icon: 'users' },
      { href: '/admin/credits', labelKey: 'navCredits', requires: 'viewer', icon: 'credits' },
    ],
  },
  {
    labelKey: 'groupPlatform',
    items: [
      { href: '/admin/config', labelKey: 'navConfig', requires: 'operator', icon: 'config' },
      { href: '/admin/data', labelKey: 'navData', requires: 'operator', icon: 'data' },
      { href: '/admin/audit', labelKey: 'navAudit', requires: 'viewer', icon: 'audit' },
      {
        href: '/admin/announcements',
        labelKey: 'navAnnouncements',
        requires: 'operator',
        icon: 'announcements',
      },
    ],
  },
];

export function visibleGroups(role: AdminRole): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => atLeast(role, item.requires)),
  })).filter((group) => group.items.length > 0);
}
