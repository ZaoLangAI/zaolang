'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Select, Switch, TextInput } from '@/components/ui/field';
import { adminApi } from '@/lib/api/admin-client';
import type { AgentProfile, ProfileBinding } from '@/lib/api/admin-types';

/**
 * Renders one node type's Pydantic config schema (fetched as JSON Schema from
 * `GET /v1/admin/workflow-templates/node-types`) as an editable form.
 *
 * Deliberately schema-driven rather than one hand-built form per node type:
 * every `NodeConfig` in `app/workflows/configs.py` is a handful of scalar
 * fields (`extra="forbid"`, no nesting), so a generic renderer covers all of
 * them today and automatically covers the next one a backend PR adds.
 *
 * The exception is `profile_bindings`: those fields are strings in the schema
 * but only a handful of values are valid, and typing one wrong is exactly the
 * mistake that would silently fall back to the default prompt. They get a
 * picker fed by the live variant list instead.
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
  profileBindings = [],
  value,
  disabled,
  onChange,
}: {
  schema: NodeConfigSchema;
  profileBindings?: ProfileBinding[];
  value: Record<string, unknown>;
  disabled?: boolean;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const properties = schema.properties ?? {};
  const entries = Object.entries(properties);
  const bindingByField = new Map(profileBindings.map((binding) => [binding.config_field, binding]));

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

        const binding = bindingByField.get(key);
        if (binding) {
          return (
            <AgentProfileSelect
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
 * Picks one of a role's agent variants for this node.
 *
 * An empty selection is not "no prompt" — it means the role's default
 * variant, which is what every node did before variants existed. Disabled
 * variants are listed but not selectable, so an operator can see why a
 * previously working binding is now flagged.
 */
function AgentProfileSelect({
  binding,
  label,
  value,
  disabled,
  onChange,
}: {
  binding: ProfileBinding;
  label: string;
  value: string;
  disabled?: boolean;
  onChange: (next: string) => void;
}) {
  const t = useTranslations('adminWorkflows');
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    adminApi
      .get<{ items: AgentProfile[] }>('/v1/admin/agent-profiles', {
        query: { role: binding.role },
      })
      .then((page) => {
        if (!cancelled) setProfiles(page.items);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [binding.role]);

  const defaultProfile = profiles.find((profile) => profile.is_default);
  const options = [
    {
      value: '',
      label: defaultProfile
        ? t('profileDefaultOption', { name: defaultProfile.display_name })
        : t('profileDefaultOptionPlain'),
    },
    ...profiles
      .filter((profile) => !profile.is_default)
      .map((profile) => ({
        value: profile.key,
        label: profile.enabled
          ? `${profile.display_name} (${profile.key})`
          : `${profile.display_name} (${profile.key}) · ${t('profileDisabledOption')}`,
        disabled: !profile.enabled && profile.key !== value,
      })),
    // A graph can reference a variant that has since been deleted. Keeping it
    // in the list is what makes the mismatch visible instead of the picker
    // quietly snapping back to "default".
    ...(value && !profiles.some((profile) => profile.key === value)
      ? [{ value, label: t('profileMissingOption', { key: value }) }]
      : []),
  ];

  return (
    <Select
      label={label}
      hint={failed ? t('profileLoadFailed') : t('profileSelectHint', { slot: binding.slot })}
      disabled={disabled}
      value={value}
      options={options}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}
