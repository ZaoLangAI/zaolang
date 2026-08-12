/**
 * Where a skill's `tool_grants` names get their labels.
 *
 * The identifiers themselves are the authoritative source (`GET
 * /agent-skill-tools`, backed by `app.agents.tools.TOOL_REGISTRY`) — this
 * only maps the four shipped names to an i18n key so the console doesn't show
 * raw Python function names.
 */
const TOOL_GRANT_LABEL_KEYS: Record<string, string> = {
  price_operation: 'toolPriceOperation',
  list_provider_capabilities: 'toolListProviderCapabilities',
  lookup_source_parameters: 'toolLookupSourceParameters',
  suggest_tags: 'toolSuggestTags',
};

/** Falls back to `null` so a tool added to the backend registry before the
 * front end knows about it still renders as its raw identifier. */
export function toolGrantLabelKey(tool: string): string | null {
  return TOOL_GRANT_LABEL_KEYS[tool] ?? null;
}
