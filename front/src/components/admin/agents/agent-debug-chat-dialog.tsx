'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { LiveThinking } from '@/components/ai/thinking-disclosure';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextArea } from '@/components/ui/field';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { copyEditorSlot } from '@/lib/admin/copy-routing';
import { getAdminToken } from '@/lib/api/admin-client';
import type { AgentNode, AgentProfile } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';
import { streamPost } from '@/lib/sse-post';

// `debug-chat` is a `StreamingResponse` (see `agent_skills.py`), so its final
// frame never appears as a schema in `openapi.json` — this mirrors
// `AgentDebugChatResponse` on the backend by hand, the same way
// `ScriptTurnCompleteEvent` does for the script-studio SSE stream.
interface DebugChatResponse {
  reply_text: string;
  parsed_json: Record<string, unknown> | null;
  degraded: boolean;
  model: string;
  latency_ms: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  agent_run_id: string;
}
type Source = 'draft' | 'published';

const INPUT_MAX_LENGTH = 4000;

interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
  degraded?: boolean;
  model?: string;
  latencyMs?: number;
  parsedJson?: Record<string, unknown> | null;
}

/**
 * Independent multi-turn debugging for one agent's system prompt.
 *
 * Never a free-form chatbot: every reply shown is the same structured
 * judgement the agent returns in production (`parsed_json`), because that
 * structure — not prose — is what an operator is here to evaluate. Stateless
 * on the server, so each send resends the whole conversation so far
 * (`POST .../debug-chat`), the same shape the shortform clarify flow already
 * uses for its own multi-turn exchanges.
 *
 * "Independent" from the skill editor: opening it from inside the editor
 * passes in the unsaved draft (`draftPromptTemplate`) so a prompt can be
 * tried before it is ever published, but this dialog is a standalone
 * conversation, not a tab embedded in the editor.
 */
export function AgentDebugChatDialog({
  profile,
  node,
  draftPromptTemplate,
  onClose,
}: {
  profile: AgentProfile;
  node: AgentNode;
  /** The skill editor's unsaved draft, when opened from inside it. Leave
   * unset to only offer debugging the currently published version. */
  draftPromptTemplate?: string;
  onClose: () => void;
}) {
  const t = useTranslations('adminAgents');
  const tAdmin = useTranslations('admin');
  const slots = node.prompt_slots ?? [];
  const isCopyRole = profile.role === 'copy';

  const [slot, setSlot] = useState(
    isCopyRole ? copyEditorSlot(profile) : (slots[0]?.key ?? 'default'),
  );
  const [source, setSource] = useState<Source>(draftPromptTemplate ? 'draft' : 'published');
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [liveThinking, setLiveThinking] = useState('');
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // Lets an operator start typing the moment the dialog opens instead of
  // having to click into the message field first.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Keeps the transcript pinned to the newest turn — including while the
  // reply is still streaming in, so a reasoning-heavy call doesn't leave the
  // reader stranded above the fold until it finishes.
  useEffect(() => {
    const node = listRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [turns.length, busy, liveThinking]);

  const reset = () => {
    setTurns([]);
    setError(null);
  };

  const send = async () => {
    const message = input.trim();
    if (!message || busy) return;
    const history: ChatTurn[] = [...turns, { role: 'user', content: message }];
    setTurns(history);
    setInput('');
    setBusy(true);
    setLiveThinking('');
    setError(null);
    try {
      let response: DebugChatResponse | null = null;
      for await (const frame of streamPost(
        `/v1/admin/agent-profiles/${profile.id}/debug-chat`,
        {
          slot,
          prompt_template: source === 'draft' ? draftPromptTemplate : undefined,
          messages: history.map(({ role, content }) => ({ role, content })),
        },
        undefined,
        { getToken: getAdminToken },
      )) {
        if (frame.event === 'thinking' && typeof frame.data.text === 'string') {
          setLiveThinking((current) => current + frame.data.text);
        } else if (frame.event === 'complete') {
          response = frame.data as unknown as DebugChatResponse;
        } else if (frame.event === 'error') {
          const message =
            typeof frame.data.message === 'string' ? frame.data.message : tAdmin('loadFailed');
          throw new Error(message);
        }
      }
      if (!response) throw new Error(tAdmin('loadFailed'));
      setTurns([
        ...history,
        {
          role: 'assistant',
          content: response.reply_text,
          degraded: response.degraded,
          model: response.model,
          latencyMs: response.latency_ms,
          parsedJson: response.parsed_json ?? null,
        },
      ]);
      setLiveThinking('');
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : caught instanceof Error
            ? caught.message
            : tAdmin('loadFailed'),
      );
      // Drop the turn that never got a reply so retrying resends cleanly.
      setTurns(turns);
    } finally {
      setBusy(false);
      // The reply landed but focus may have drifted to the send button;
      // pull it back so the next turn can be typed immediately.
      inputRef.current?.focus();
    }
  };

  // Enter sends, Shift+Enter inserts a newline — but not while an IME
  // composition (e.g. pinyin candidate selection) is still open, where
  // Enter only confirms the candidate and must not submit the message.
  const handleInputKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void send();
  };

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title={t('debugChat')}
      description={`${profile.display_name} · ${node.display_name}`}
      footer={
        <div className="flex w-full items-end gap-2">
          {/* `min-w-0 flex-1`, not just `w-full` on the textarea itself: a
              flex item's default basis comes from its content, not its
              child's percentage width, so without this wrapper the field
              sits at its intrinsic ~20-column width regardless of how wide
              the dialog (and thus the footer row) actually is. */}
          <div className="min-w-0 flex-1">
            <TextArea
              ref={inputRef}
              label={t('debugChatInput')}
              hint={t('debugChatInputHint', { count: input.length, max: INPUT_MAX_LENGTH })}
              value={input}
              maxLength={INPUT_MAX_LENGTH}
              className="min-h-16"
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleInputKeyDown}
            />
          </div>
          <Button loading={busy} disabled={input.trim().length === 0} onClick={() => void send()}>
            {t('debugChatSend')}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          {slots.length > 1 && !isCopyRole ? (
            <div className="min-w-44 flex-1">
              <Select
                label={t('promptSlot')}
                value={slot}
                onChange={(event) => {
                  setSlot(event.target.value);
                  reset();
                }}
                options={slots.map((candidate) => ({
                  value: candidate.key,
                  label: candidate.label,
                }))}
              />
            </div>
          ) : null}
          <div className="min-w-44 flex-1">
            <Select
              label={t('debugChatSource')}
              value={source}
              disabled={!draftPromptTemplate}
              hint={!draftPromptTemplate ? t('debugChatSourceNoDraft') : undefined}
              onChange={(event) => {
                setSource(event.target.value as Source);
                reset();
              }}
              options={[
                { value: 'published', label: t('debugChatSourcePublished') },
                { value: 'draft', label: t('debugChatSourceDraft') },
              ]}
            />
          </div>
        </div>

        <ul
          ref={listRef}
          className="flex min-h-[320px] max-h-[55vh] flex-col gap-2 overflow-y-auto rounded-[var(--radius-sm)] border border-border p-3"
        >
          {turns.length === 0 ? (
            <p className="m-auto max-w-xs text-center text-xs text-muted">{t('debugChatEmpty')}</p>
          ) : (
            turns.map((turn, index) => (
              <li
                key={index}
                className={
                  turn.role === 'user'
                    ? 'ml-auto max-w-[85%] rounded-[var(--radius-sm)] bg-accent-soft px-3 py-2 text-sm text-text'
                    : 'max-w-[85%] rounded-[var(--radius-sm)] border border-border bg-surface px-3 py-2 text-sm text-text'
                }
              >
                {turn.role === 'assistant' ? (
                  <div className="mb-1 flex flex-wrap items-center gap-1.5">
                    {turn.degraded ? <Badge tone="amber">{t('degraded')}</Badge> : null}
                    {turn.model ? (
                      <span className="font-mono text-[11px] text-muted">{turn.model}</span>
                    ) : null}
                    {turn.latencyMs != null ? (
                      <span className="text-[11px] text-muted">{turn.latencyMs}ms</span>
                    ) : null}
                  </div>
                ) : null}
                {turn.role === 'assistant' && turn.parsedJson ? (
                  <pre className="whitespace-pre-wrap break-words font-mono text-xs">
                    {JSON.stringify(turn.parsedJson, null, 2)}
                  </pre>
                ) : (
                  <p className="whitespace-pre-wrap break-words">{turn.content}</p>
                )}
              </li>
            ))
          )}
          {busy ? (
            <li className="max-w-[85%]">
              <LiveThinking
                thinking={liveThinking}
                label={t('thinkingLive')}
                className="max-h-32 overflow-y-auto"
              />
            </li>
          ) : null}
        </ul>

        {error ? <ErrorNotice title={error} /> : null}
      </div>
    </Dialog>
  );
}
