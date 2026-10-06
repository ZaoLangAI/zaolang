/** The workspace tabs (`asset-workspace.tsx`). Kept out of the client
 * module so the route pages (server components) can parse `?tab=`. */
export type WorkspaceTab = 'create' | 'looks' | 'voices';

export function parseWorkspaceTab(value: string | undefined): WorkspaceTab | null {
  return value === 'create' || value === 'looks' || value === 'voices' ? value : null;
}
