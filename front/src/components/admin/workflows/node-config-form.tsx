'use client';

import { Select, Switch, TextInput } from '@/components/ui/field';

/**
 * Renders one node type's Pydantic config schema (fetched as JSON Schema from
 * `GET /v1/admin/workflow-templates/node-types`) as an editable form.
 *
 * Deliberately schema-driven rather than one hand-built form per node type:
 * every `NodeConfig` in `app/workflows/configs.py` is a handful of scalar
 * fields (`extra="forbid"`, no nesting), so a generic renderer covers all of
 * them today and automatically covers the next one a backend PR adds.
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
  value,
  disabled,
  onChange,
}: {
  schema: NodeConfigSchema;
  value: Record<string, unknown>;
  disabled?: boolean;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const properties = schema.properties ?? {};
  const entries = Object.entries(properties);

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
