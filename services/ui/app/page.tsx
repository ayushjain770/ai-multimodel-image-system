"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteSession,
  getHistory,
  listSessions,
  mediaUrl,
  streamChat,
  type ChatMessage,
  type Denomination,
  type IntentInfo,
  type SessionSummary,
} from "@/lib/api";

interface Turn extends ChatMessage {
  image?: string | null;
  imageUrl?: string | null;
  intent?: IntentInfo | null;
  intentKind?: string | null;
  streaming?: boolean;
}

const DENOMINATIONS: Denomination[] = [
  "neutral",
  "catholic",
  "protestant",
  "orthodox",
];

const SESSION_KEY = "christ-ai.session-id";

function newSessionId(): string {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `sess-${Math.random().toString(36).slice(2)}`
  );
}

export default function Home() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [generateImage, setGenerateImage] = useState(false);
  const [denomination, setDenomination] = useState<Denomination>("neutral");
  const [sessionId, setSessionId] = useState<string>("");
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Index of the assistant bubble currently being streamed into.
  const replyIdx = useRef<number>(-1);

  function updateReply(patch: (t: Turn) => Turn) {
    setTurns((prev) =>
      prev.map((t, i) => (i === replyIdx.current ? patch(t) : t)),
    );
  }

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await listSessions());
    } catch {
      // Durable store may be disabled; the sidebar simply stays empty.
      setSessions([]);
    }
  }, []);

  // Restore the last active session id (or mint one) and load the list.
  useEffect(() => {
    const stored =
      globalThis.localStorage?.getItem(SESSION_KEY) ?? newSessionId();
    setSessionId(stored);
    globalThis.localStorage?.setItem(SESSION_KEY, stored);
    void refreshSessions();
  }, [refreshSessions]);

  function activate(id: string) {
    setSessionId(id);
    globalThis.localStorage?.setItem(SESSION_KEY, id);
  }

  function newChat() {
    activate(newSessionId());
    setTurns([]);
    setError(null);
  }

  async function selectSession(id: string) {
    if (id === sessionId || loading) return;
    setError(null);
    activate(id);
    try {
      const history = await getHistory(id);
      setTurns(
        history.map((h) => ({
          role: h.role,
          content: h.content,
          intentKind: h.intent_kind,
          imageUrl: mediaUrl(h.image_url),
        })),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load session");
      setTurns([]);
    }
  }

  async function removeSession(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    try {
      await deleteSession(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete session");
    }
    await refreshSessions();
    if (id === sessionId) newChat();
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const message = input.trim();
    if (!message || loading) return;

    setError(null);
    setLoading(true);
    const history: ChatMessage[] = turns.map(({ role, content }) => ({
      role,
      content,
    }));
    setInput("");

    setTurns((t) => {
      const next: Turn[] = [
        ...t,
        { role: "user", content: message },
        { role: "assistant", content: "", streaming: true },
      ];
      replyIdx.current = next.length - 1;
      return next;
    });

    try {
      await streamChat(message, history, generateImage, sessionId, denomination, {
        onMeta: (meta) => updateReply((t) => ({ ...t, intent: meta.intent })),
        onToken: (delta) =>
          updateReply((t) => ({ ...t, content: t.content + delta })),
        onFinal: (final) =>
          updateReply((t) => ({
            ...t,
            content: final.reply,
            image: final.image_base64,
            imageUrl: mediaUrl(final.image_url),
            streaming: false,
          })),
        onError: (msg) => setError(msg),
      });
      void refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
      updateReply((t) => ({ ...t, streaming: false }));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <button className="new-chat" onClick={newChat} type="button">
          + New chat
        </button>
        <div className="session-list">
          {sessions.length === 0 ? (
            <p className="muted empty">No conversations yet</p>
          ) : (
            sessions.map((s) => (
              <div
                key={s.session_id}
                className={`session-item ${
                  s.session_id === sessionId ? "active" : ""
                }`}
                onClick={() => void selectSession(s.session_id)}
              >
                <div className="session-text">
                  <span className="session-preview">
                    {s.preview || "(empty)"}
                  </span>
                  <span className="muted session-meta">
                    {s.turns} turn{s.turns === 1 ? "" : "s"} · {s.denomination}
                  </span>
                </div>
                <button
                  className="session-delete"
                  onClick={(e) => void removeSession(s.session_id, e)}
                  aria-label="delete conversation"
                  type="button"
                >
                  ×
                </button>
              </div>
            ))
          )}
        </div>
      </aside>

      <main className="shell">
        <h1>Christianity AI Assistant</h1>
        <p className="muted">
          Streaming chat with memory, denomination framing, and images
        </p>

        <div className="messages">
          {turns.map((turn, i) => {
            const badge = turn.intent?.kind ?? turn.intentKind;
            return (
              <div key={i} className={`bubble ${turn.role}`}>
                {turn.role === "assistant" && badge ? (
                  <span className="badge">{badge}</span>
                ) : null}
                {turn.content}
                {turn.streaming && !turn.content ? (
                  <span className="muted">
                    {badge === "image"
                      ? "Generating artwork…"
                      : "thinking..."}
                  </span>
                ) : null}
                {turn.imageUrl ? (
                  <img src={turn.imageUrl} alt="generated" />
                ) : turn.image ? (
                  <img
                    src={`data:image/png;base64,${turn.image}`}
                    alt="generated"
                  />
                ) : null}
              </div>
            );
          })}
          {error ? <div className="bubble assistant">Error: {error}</div> : null}
        </div>

        <form onSubmit={onSubmit}>
          <input
            type="text"
            value={input}
            placeholder="Ask something..."
            onChange={(e) => setInput(e.target.value)}
          />
          <select
            value={denomination}
            onChange={(e) => setDenomination(e.target.value as Denomination)}
            aria-label="denomination"
          >
            {DENOMINATIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <label className="toggle">
            <input
              type="checkbox"
              checked={generateImage}
              onChange={(e) => setGenerateImage(e.target.checked)}
            />
            image
          </label>
          <button type="submit" disabled={loading}>
            Send
          </button>
        </form>
      </main>
    </div>
  );
}
