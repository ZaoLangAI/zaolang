'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Select, Switch, TextInput } from '@/components/ui/field';
import { adminApi } from '@/lib/api/admin-client';
import type { AgentBinding, AgentProfile } from '@/lib/api/admin-types';

/**
 * Renders one node type's Pydantic config schema (fetched as JSON Schema from
 * `GET /v1/admin/workflow-templates/node-types`) as an editable form.
 *
 * Deliberately schema-driven rather than one hand-built form per node type:
 * every `NodeConfig` in `app/workflows/configs.py` is a handful of scalar
 * fields (`extra="forbid"`, no nesting), so a generic renderer covers all of
 * them today and automatically covers the next one a backend PR adds.
 *
 * The exception is the agent bindings: those fields hold an agent id, which is
 * a string in the schema but only ever one of a short list, and picking the
 * wrong one is exactly the mistake that would silently fall back to the role's
 * default prompt. They get a picker fed by the live agent list instead —
 * `agent_bindings` names the ones filtered to a role the node type requires,
 * and `creative_agent_id` the one filtered by category, since creative roles
 * are operator-created and their names are not fixed at code-review time.
 */

/** Config field naming a creative agent — see `RouteScoreConfig`. */
const CREATIVE_AGENT_FIELD = 'creative_agent_id';

export interface JsonSchemaProperty {
  type?: 'string' | 'integer' | 'number' | 'boolean' | 'array' | 'null';
  enum?: string[];
  anyOf?: JsonSchemaProperty[];
  items?: JsonSchemaProperty;
  default?: unknown;
  title?: string;
  minimum?: number;
  maximum?: number;
}

export interface NodeConfigSchema {
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
}

type ConfigValue = string | number | boolean | string[] | null | undefined;

function resolveType(prop: JsonSchemaProperty): {
  type: 'string' | 'integer' | 'number' | 'boolean' | 'array' | 'enum';
  nullable: boolean;
  enum?: string[];
  minimum?: number;
  maximum?: number;
} {
  if (prop.enum) return { type: 'enum', nullable: false, enum: prop.enum };
  if (prop.anyOf) {
    const nullable = prop.anyOf.some((branch) => branch.type === 'null');
    const real = prop.anyOf.find((branch) => branch.type && branch.type !== 'null') ?? prop;
    const resolved = resolveType(real);
    return { ...resolved, nullable };
  }
  if (prop.type === 'array') return { type: 'array', nullable: false };
  if (prop.type === 'boolean') return { type: 'boolean', nullable: false };
  if (prop.type === 'integer' || prop.type === 'number') {
    return { type: prop.type, nullable: false, minimum: prop.minimum, maximum: prop.maximum };
  }
  return { type: 'string', nullable: false };
}

export function NodeConfigForm({
  schema,
  agentBindings = [],
  value,
  disabled,
  onChange,
}: {
  schema: NodeConfigSchema;
  agentBindings?: AgentBinding[];
  value: Record<string, unknown>;
  disabled?: boolean;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const properties = schema.properties ?? {};
  const entries = Object.entries(properties);
  const bindingByField = new Map(agentBindings.map((binding) => [binding.config_field, binding]));

  if (entries.length === 0) {
    return null;
  }

  const set = (key: string, next: ConfigValue) => onChange({ ...value, [key]: next });

  return (
    <div className="flex flex-col gap-3">
      {entries.map(([key, prop]) => {
        const resolved = resolveType(prop);
        const label = prop.title ?? key;
        const current = value[key];

        if (key === CREATIVE_AGENT_FIELD) {
          return (
            <CreativeAgentSelect
              key={key}
              label={label}
              value={typeof current === 'string' ? current : ''}
              disabled={disabled}
              onChange={(next) => set(key, next || null)}
            />
          );
        }

        const binding = bindingByField.get(key);
        if (binding) {
          return (
            <AgentSelect
              key={key}
              binding={binding}
              label={label}
              value={typeof current === 'string' ? current : ''}
              disabled={disabled}
              onChange={(next) => set(key, next || null)}
            />
          );
        }

        if (resolved.type === 'boolean') {
          return (
            <Switch
              key={key}
              label={label}
              checked={Boolean(current ?? prop.default ?? false)}
              disabled={disabled}
              onChange={(next) => set(key, next)}
            />
          );
        }

        if (resolved.type === 'enum' && resolved.enum) {
          return (
            <Select
              key={key}
              label={label}
              disabled={disabled}
              value={String(current ?? prop.default ?? resolved.enum[0])}
              onChange={(event) => set(key, event.target.value)}
              options={resolved.enum.map((option) => ({ value: option, label: option }))}
            />
          );
        }

        if (resolved.type === 'array') {
          const items = Array.isArray(current) ? (current as string[]) : [];
          return (
            <TextInput
              key={key}
              label={label}
              disabled={disabled}
              value={items.join(', ')}
              onChange={(event) =>
                set(
                  key,
                  event.target.value
                    .split(',')
                    .map((item) => item.trim())
                    .filter(Boolean),
                )
              }
            />
          );
        }

        if (resolved.type === 'integer' || resolved.type === 'number') {
          const raw = current ?? prop.default;
          return (
            <TextInput
              key={key}
              label={label}
              type="number"
              min={resolved.minimum}
              max={resolved.maximum}
              disabled={disabled}
              value={raw === null || raw === undefined ? '' : String(raw)}
              placeholder={resolved.nullable ? '—' : undefined}
              onChange={(event) => {
                const text = event.target.value;
                if (text === '') {
                  set(key, resolved.nullable ? null : undefined);
                  return;
                }
                const parsed = resolved.type === 'integer' ? parseInt(text, 10) : parseFloat(text);
                if (!Number.isNaN(parsed)) set(key, parsed);
              }}
            />
          );
        }

        return (
          <TextInput
            key={key}
            label={label}
            disabled={disabled}
            value={String(current ?? prop.default ?? '')}
            onChange={(event) => set(key, event.target.value)}
          />
        );
      })}
    </div>
  );
}

/**
 * Picks which agent runs this node, out of the ones whose role it accepts.
 *
 * An empty selection is not "no prompt" — it means the role's default agent,
 * which is what every node did before more than one agent per role existed.
 * Disabled agents are listed but not selectable, so an operator can see why a
 * previously working binding is now flagged.
 */
function AgentSelect({
  binding,
  label,
  value,
  disabled,
  onChange,
}: {
  binding: AgentBinding;
  label: string;
  value: string;
  disabled?: boolean;
  onChange: (next: string) => void;
}) {
  const t = useTranslations('adminWorkflows');
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    adminApi
      .get<{ items: AgentProfile[] }>('/v1/admin/agent-profiles', {
        query: { role: binding.role },
      })
      .then((page) => {
        if (!cancelled) setAgents(page.items);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [binding.role]);

  const fallback = agents.find((agent) => agent.is_default);
  const options = [
    {
      value: '',
      label: fallback
        ? t('agentDefaultOption', { name: fallback.display_name })
        : t('agentDefaultOptionPlain'),
    },
    ...agents
      .filter((agent) => !agent.is_default)
      .map((agent) => ({
        value: agent.id,
        label: agent.enabled
          ? agent.display_name
          : `${agent.display_name} · ${t('agentDisabledOption')}`,
        disabled: !agent.enabled && agent.id !== value,
      })),
    // A graph can reference an agent that has since been deleted. Keeping it
    // in the list is what makes the mismatch visible instead of the picker
    // quietly snapping back to "default".
    ...(value && !agents.some((agent) => agent.id === value)
      ? [{ value, label: t('agentMissingOption', { id: value }) }]
      : []),
  ];

  return (
    <Select
      label={label}
      hint={failed ? t('agentLoadFailed') : t('agentSelectHint', { slot: binding.slot })}
      disabled={disabled}
      value={value}
      options={options}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

/**
 * Picks the creative agent whose media candidates narrow this node's routing.
 *
 * Empty means the full catalogue, which is what routing did before creative
 * agents existed. The candidates and their cost weights are context the
 * routing agent reads — they never rank candidates on their own.
 */
function CreativeAgentSelect({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  disabled?: boolean;
  onChange: (next: string) => void;
}) {
  const t = useTranslations('adminWorkflows');
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    adminApi
      .get<{ items: AgentProfile[] }>('/v1/admin/agent-profiles')
      .then((page) => {
        if (!cancelled) setAgents(page.items.filter((item) => item.category === 'creative'));
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const options = [
    { value: '', label: t('creativeAgentNone') },
    ...agents.map((agent) => ({
      value: agent.id,
      label: agent.enabled
        ? `${agent.display_name} (${agent.role})`
        : `${agent.display_name} (${agent.role}) · ${t('agentDisabledOption')}`,
      disabled: !agent.enabled && agent.id !== value,
    })),
    // Same reasoning as the agent picker: a graph can outlive the agent it
    // references, and hiding that would look like "no narrowing configured".
    ...(value && !agents.some((agent) => agent.id === value)
      ? [{ value, label: t('agentMissingOption', { id: value }) }]
      : []),
  ];

  return (
    <Select
      label={label}
      hint={failed ? t('agentLoadFailed') : t('creativeAgentHint')}
      disabled={disabled}
      value={value}
      options={options}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}
