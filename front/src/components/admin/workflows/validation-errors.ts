/**
 * Best-effort extraction of the node id a backend validation message is
 * about, so the canvas can outline the offending node instead of leaving the
 * operator to match free text against a graph by eye.
 *
 * `workflow_templates.service` and `workflows.graph.validate` never emit a
 * structured `{node_id, message}` pair — every message is Chinese prose with
 * the id embedded — so this parses it back out with the same patterns those
 * two modules use to build the string. Getting a message wrong here only
 * costs a missed outline, never a false rejection: nothing downstream acts
 * on the parsed id except CSS.
 */
const NODE_ID_PATTERNS: RegExp[] = [
  // "节点 id 重复: {id}" — the one message where "节点" is followed by the
  // literal word "id", not an id, so it must be checked before the generic
  // "节点 <id>" pattern below.
  /^节点 id 重复[:：]\s*(\S+)/,
  // "未知节点类型: {type} ({id})"
  /未知节点类型[:：].*?\((\S+)\)/,
  // Every other node-scoped message: "节点 {id} 的输出端口…" / "节点 {id} 绑定了…" / …
  /^节点\s+(\S+)/,
];

export function parseNodeId(message: string): string | null {
  for (const pattern of NODE_ID_PATTERNS) {
    const match = message.match(pattern);
    if (match?.[1]) return match[1];
  }
  return null;
}

export function parseNodeIds(messages: string[]): Set<string> {
  const ids = new Set<string>();
  for (const message of messages) {
    const id = parseNodeId(message);
    if (id) ids.add(id);
  }
  return ids;
}

/** Groups messages by the node they are about, for a per-node "what's wrong
 * here" list in the canvas sidebar. Graph-level messages (no node id, e.g.
 * "must have exactly one entry node") are dropped — they have nowhere to be
 * shown next to a single node. */
export function groupErrorsByNode(messages: string[]): Map<string, string[]> {
  const grouped = new Map<string, string[]>();
  for (const message of messages) {
    const id = parseNodeId(message);
    if (!id) continue;
    const list = grouped.get(id);
    if (list) list.push(message);
    else grouped.set(id, [message]);
  }
  return grouped;
}
