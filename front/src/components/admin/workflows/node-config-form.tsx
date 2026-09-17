'use client';

import { useTranslations } from 'next-intl';

import {
  describeAgent,
  useAgentCatalog,
  type AgentCatalog,
} from '@/components/admin/workflows/agent-catalog';
import { Select, Switch, TextInput } from '@/components/ui/field';
import type { AgentBinding, DynamicAgentBinding, NodeTypeView } from '@/lib/api/admin-types';

/**
 * Renders one node type's Pydantic config schema (fetched as JSON Schema from
 * `GET /v1/admin/workflow-templates/node-types`) as an editable form.
 *
 * Deliberately schema-driven rather than one hand-built form per node type:
 * every `NodeConfig` in `app/workflows/configs.py` is a handful of scalar
 * fields (`extra="forbid"`, no nesting), so a generic renderer covers all of
 * them today and automatically covers the next one a backend PR adds.
 *
 * The exception is the agent bindings. Those fields hold an agent id, which
 * is a string in the schema but only ever one of a short list, and picking
 * the wrong one is exactly the mistake that would silently fall back to the
 * role's default prompt. Which fields those are is *declared by the backend*
 * (`registry.NodeSpec`), in three flavours the spec exposes separately:
 *
 * - `agent_bindings` — the role is fixed by the node type.
 * - `dynamic_agent_binding` — the role is itself a config field, because the
 *   whole point of `custom_agent` is running a role created in the console.
 *
 * Nothing here matches on a field name: adding a third such field to a node
 * type is a backend-only change.
 */

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

/**
 * `fail.default_code` — the failure code a job that reaches this node is
 * closed out with. There is no backend enum to import (job failure codes are
 * string literals scattered across `workflows/nodes.py` /
 * `workers/tasks.py`, unlike the `DomainError.code` table `errors.py` owns
 * for API responses), so this is a curated list of the codes those modules
 * actually assign today, kept as a starting point rather than a closed set —
 * the field stays a free string underneath, this only adds a picker for the
 * common cases and always keeps whatever is already there as an option.
 */
const KNOWN_FAILURE_CODES = [
  'PROVIDER_TEMPORARY_FAILURE',
  'MODERATION_REJECTED',
  'QUALITY_REJECTED',
  'WORKFLOW_MISCONFIGURED',
] as const;

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
  spec,
  value,
  disabled,
  availablePorts,
  onChange,
}: {
  spec: NodeTypeView;
  value: Record<string, unknown>;
  disabled?: boolean;
  /** Every output port reachable on the branches feeding this node, for the
   * `join` node's success-port picker. */
  availablePorts?: string[];
  onChange: (next: Record<string, unknown>) => void;
}) {
  const catalog = useAgentCatalog();
  const schema = spec.config_schema as unknown as NodeConfigSchema;
  const properties = schema.properties ?? {};
  const entries = Object.entries(properties);

  const roleBindings = new Map(
    (spec.agent_bindings ?? []).map((binding) => [binding.config_field, binding]),
  );
  const dynamic = spec.dynamic_agent_binding ?? null;

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

        if (dynamic && key === dynamic.config_field) {
          return (
            <DynamicAgentFields
              key={key}
              binding={dynamic}
              catalog={catalog}
              disabled={disabled}
              role={
                typeof value[dynamic.role_field] === 'string'
                  ? String(value[dynamic.role_field])
                  : ''
              }
              agentId={typeof current === 'string' ? current : ''}
              slot={
                typeof value[dynamic.slot_field] === 'string'
                  ? String(value[dynamic.slot_field])
                  : ''
              }
              onChange={(next) => onChange({ ...value, ...next })}
            />
          );
        }
        // The role and slot are rendered by `DynamicAgentFields` above, as
        // part of the cascade — not as two more standalone text boxes.
        if (dynamic && (key === dynamic.role_field || key === dynamic.slot_field)) {
          return null;
        }

        const roleBinding = roleBindings.get(key);
        if (roleBinding) {
          return (
            <AgentSelect
              key={key}
              binding={roleBinding}
              catalog={catalog}
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
          if (availablePorts && availablePorts.length > 0) {
            return (
              <PortChecklist
                key={key}
                label={label}
                ports={availablePorts}
                selected={items.length > 0 ? items : ((prop.default as string[]) ?? [])}
                disabled={disabled}
                onChange={(next) => set(key, next)}
              />
            );
          }
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

        if (spec.type === 'fail' && key === 'default_code') {
          const code = String(current ?? prop.default ?? KNOWN_FAILURE_CODES[0]);
          return (
            <Select
              key={key}
              label={label}
              disabled={disabled}
              value={code}
              options={[
                ...KNOWN_FAILURE_CODES.map((option) => ({ value: option, label: option })),
                ...(KNOWN_FAILURE_CODES.includes(code as (typeof KNOWN_FAILURE_CODES)[number])
                  ? []
                  : [{ value: code, label: code }]),
              ]}
              onChange={(event) => set(key, event.target.value)}
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

/** The options every agent picker shares: a "role default" entry naming the
 * agent that would actually run, then the rest, then — crucially — the bound
 * id itself when it no longer resolves, because a graph can outlive the agent
 * it references and quietly snapping back to "default" would hide that. */
function agentOptions(
  profiles: ReturnType<AgentCatalog['profilesOf']>,
  value: string,
  labels: { fallback: string; disabled: string; missing: (id: string) => string },
  describe: (profile: (typeof profiles)[number]) => string = describeAgent,
) {
  return [
    { value: '', label: labels.fallback },
    ...profiles
      .filter((profile) => !profile.is_default)
      .map((profile) => ({
        value: profile.id,
        label: profile.enabled ? describe(profile) : `${describe(profile)} · ${labels.disabled}`,
        disabled: !profile.enabled && profile.id !== value,
      })),
    ...(value && !profiles.some((profile) => profile.id === value)
      ? [{ value, label: labels.missing(value) }]
      : []),
  ];
}

/**
 * Picks which agent runs this node, out of the ones whose role it accepts.
 *
 * An empty selection is not "no prompt" — it means the role's default agent.
 * That is a safe choice by construction: a default judgment agent is required
 * to carry a model binding (`agent_skills.service._apply_bindings`), so the
 * option names it and its model rather than leaving an operator guessing
 * whether blank means unconfigured.
 */
function AgentSelect({
  binding,
  catalog,
  label,
  value,
  disabled,
  onChange,
}: {
  binding: AgentBinding;
  catalog: AgentCatalog;
  label: string;
  value: string;
  disabled?: boolean;
  onChange: (next: string) => void;
}) {
  const t = useTranslations('adminWorkflows');
  const profiles = catalog.profilesOf(binding.role);
  const fallback = catalog.defaultProfileOf(binding.role);

  return (
    <Select
      label={label}
      hint={t('agentSelectHint', { slot: binding.slot })}
      disabled={disabled}
      value={value}
      options={agentOptions(profiles, value, {
        fallback: fallback
          ? t('agentDefaultOption', { name: describeAgent(fallback) })
          : t('agentDefaultOptionPlain'),
        disabled: t('agentDisabledOption'),
        missing: (id) => t('agentMissingOption', { id }),
      })}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

/**
 * The `custom_agent` cascade: role, then that role's agents, then that role's
 * prompt slots.
 *
 * All three used to be free-text boxes, which meant typing a 40-character
 * `ap_…` id by hand and getting no warning at all when the role did not
 * exist. Roles come from `ROLE_PRESETS` (a role no node type invokes can
 * never run) and slots from `app/agents/slots.py` via the role's node row —
 * never a hardcoded list here, since roles gain slots over time.
 *
 * Changing the role resets the agent and slot together: keeping either would
 * leave the node pointing at an agent of the wrong role, which the publish
 * check rejects and the runtime falls back out of.
 */
function DynamicAgentFields({
  binding,
  catalog,
  role,
  agentId,
  slot,
  disabled,
  onChange,
}: {
  binding: DynamicAgentBinding;
  catalog: AgentCatalog;
  role: string;
  agentId: string;
  slot: string;
  disabled?: boolean;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const t = useTranslations('adminWorkflows');
  const presets = catalog.presets;
  const profiles = role ? catalog.profilesOf(role) : [];
  const fallback = role ? catalog.defaultProfileOf(role) : undefined;
  const slots = role ? catalog.slotsOf(role) : [];

  const selectRole = (nextRole: string) =>
    onChange({
      [binding.role_field]: nextRole,
      [binding.config_field]: null,
      [binding.slot_field]: catalog.slotsOf(nextRole)[0]?.key ?? 'default',
    });

  return (
    <>
      <Select
        label={t('customAgentRole')}
        hint={t('customAgentRoleHint')}
        disabled={disabled}
        value={role}
        options={[
          { value: '', label: t('customAgentRolePlaceholder') },
          ...presets.map((preset) => ({ value: preset.role, label: preset.display_name })),
          // A role removed from the presets since publishing would otherwise
          // vanish from the dropdown and read as "nothing selected".
          ...(role && !presets.some((preset) => preset.role === role)
            ? [{ value: role, label: t('customAgentRoleUnknown', { role }) }]
            : []),
        ]}
        onChange={(event) => selectRole(event.target.value)}
      />
      <Select
        label={t('customAgentAgent')}
        disabled={disabled || !role}
        value={agentId}
        options={agentOptions(profiles, agentId, {
          fallback: fallback
            ? t('agentDefaultOption', { name: describeAgent(fallback) })
            : t('agentDefaultOptionPlain'),
          disabled: t('agentDisabledOption'),
          missing: (id) => t('agentMissingOption', { id }),
        })}
        onChange={(event) => onChange({ [binding.config_field]: event.target.value || null })}
      />
      <Select
        label={t('customAgentSlot')}
        hint={t('customAgentSlotHint')}
        disabled={disabled || !role}
        value={slot}
        options={[
          ...slots.map((candidate) => ({ value: candidate.key, label: candidate.label })),
          ...(slot && !slots.some((candidate) => candidate.key === slot)
            ? [{ value: slot, label: t('customAgentSlotUnknown', { slot }) }]
            : []),
        ]}
        onChange={(event) => onChange({ [binding.slot_field]: event.target.value })}
      />
    </>
  );
}

/**
 * Which ports count as "this branch succeeded", for a `join`.
 *
 * A comma-separated text box invited typos that silently made a barrier
 * unsatisfiable; the options are the ports the branches feeding this join can
 * actually produce.
 */
function PortChecklist({
  label,
  ports,
  selected,
  disabled,
  onChange,
}: {
  label: string;
  ports: string[];
  selected: string[];
  disabled?: boolean;
  onChange: (next: string[]) => void;
}) {
  const toggle = (port: string) =>
    onChange(
      selected.includes(port) ? selected.filter((item) => item !== port) : [...selected, port],
    );

  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="text-xs font-medium text-text">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {ports.map((port) => {
          const checked = selected.includes(port);
          return (
            <label
              key={port}
              className={
                checked
                  ? 'cursor-pointer rounded-[var(--radius-sm)] border border-primary bg-primary/12 px-2 py-1 font-mono text-[11px] text-primary'
                  : 'cursor-pointer rounded-[var(--radius-sm)] border border-border px-2 py-1 font-mono text-[11px] text-muted hover:text-text'
              }
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={checked}
                disabled={disabled}
                onChange={() => toggle(port)}
              />
              {port}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
