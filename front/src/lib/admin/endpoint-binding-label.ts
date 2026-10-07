type BindableEndpoint = { name: string; model?: string | null; input_modalities?: string[] };

/**
 * One option in an agent's provider picker: name, model, and a vision tag
 * when the endpoint declares image input. Image calls (script image extract)
 * only run on tagged endpoints, so the operator can see which pins work for
 * them.
 */
export function endpointBindingLabel(endpoint: BindableEndpoint, visionTag: string): string {
  const base = endpoint.model ? `${endpoint.name} · ${endpoint.model}` : endpoint.name;
  return endpoint.input_modalities?.includes('image') ? `${base} · ${visionTag}` : base;
}
