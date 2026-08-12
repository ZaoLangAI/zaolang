'use client';

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

import { adminApi } from '@/lib/api/admin-client';
import type { AgentNode, AgentProfile, RolePreset } from '@/lib/api/admin-types';

/**
 * The agents, roles and prompt slots the workflow editor needs, fetched once.
 *
 * Every agent picker used to fetch `/v1/admin/agent-profiles` from its own
 * effect, re-fetching whenever an operator selected a different node — with
 * `admin_read` capped at 300/60s, clicking around a graph could exhaust the
 * budget. The lists are also small and shared, so the page loads them on the
 * server (see `routing/page.tsx`) and hands them down through here.
 *
 * `prompt_slots` on a node is the API's view of `app/agents/slots.py`, which
 * is the single source of truth for which prompts a role owns. Anything that
 * offers a slot choice must read it from here rather than hardcoding one:
 * roles gain slots over time (`copy` recently gained `clarify`).
 */
export interface AgentCatalog {
  nodes: AgentNode[];
  profiles: AgentProfile[];
  presets: RolePreset[];
  /** Re-reads all three. Call after publishing a prompt or editing an agent. */
  refresh: () => Promise<void>;
  profileById: (id: string) => AgentProfile | undefined;
  /** The agent an unbound node falls back to. Judgment defaults are required
   * to carry a model binding, so this is always something that can run. */
  defaultProfileOf: (role: string) => AgentProfile | undefined;
  profilesOf: (role: string) => AgentProfile[];
  slotsOf: (role: string) => NonNullable<AgentNode['prompt_slots']>;
}

const AgentCatalogContext = createContext<AgentCatalog | null>(null);

export interface AgentCatalogSeed {
  nodes: AgentNode[];
  profiles: AgentProfile[];
  presets: RolePreset[];
}

export function AgentCatalogProvider({
  seed,
  children,
}: {
  seed: AgentCatalogSeed;
  children: ReactNode;
}) {
  const [catalog, setCatalog] = useState(seed);

  const refresh = useCallback(async () => {
    try {
      const [nodePage, profilePage, presetPage] = await Promise.all([
        adminApi.get<{ items: AgentNode[] }>('/v1/admin/agent-nodes'),
        adminApi.get<{ items: AgentProfile[] }>('/v1/admin/agent-profiles'),
        adminApi.get<{ items: RolePreset[] }>('/v1/admin/agent-node-presets'),
      ]);
      setCatalog({
        nodes: nodePage.items,
        profiles: profilePage.items,
        presets: presetPage.items,
      });
    } catch {
      // Keeping the last good catalogue beats emptying every picker: the
      // graph on the canvas still references these agents, and blanking the
      // options would read as "this binding is gone".
    }
  }, []);

  const value = useMemo<AgentCatalog>(() => {
    const byId = new Map(catalog.profiles.map((profile) => [profile.id, profile]));
    return {
      ...catalog,
      refresh,
      profileById: (id) => byId.get(id),
      defaultProfileOf: (role) =>
        catalog.profiles.find((profile) => profile.role === role && profile.is_default),
      profilesOf: (role) => catalog.profiles.filter((profile) => profile.role === role),
      slotsOf: (role) => catalog.nodes.find((node) => node.role === role)?.prompt_slots ?? [],
    };
  }, [catalog, refresh]);

  return <AgentCatalogContext.Provider value={value}>{children}</AgentCatalogContext.Provider>;
}

export function useAgentCatalog(): AgentCatalog {
  const catalog = useContext(AgentCatalogContext);
  if (catalog === null) {
    throw new Error('useAgentCatalog must be used inside an AgentCatalogProvider');
  }
  return catalog;
}

/** How an agent is named wherever a node's binding is summarised: the name an
 * operator gave it, plus the model it will actually run on — the two things
 * they are checking when they look at a node. The raw `ap_…` id belongs in a
 * tooltip, never in the text. */
export function describeAgent(profile: AgentProfile): string {
  return profile.model ? `${profile.display_name} · ${profile.model}` : profile.display_name;
}
