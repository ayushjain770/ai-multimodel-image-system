"use client";

import { useRef, useState } from "react";
import {
  streamChat,
  type ChatMessage,
  type Denomination,
  type IntentInfo,
} from "@/lib/api";

interface Turn extends ChatMessage {
  image?: string | null;
  intent?: IntentInfo | null;
  streaming?: boolean;
}

const DENOMINATIONS: Denomination[] = [
  "neutral",
  "catholic",
  "protestant",
  "orthodox",
];

export default function Home() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [generateImage, setGenerateImage] = useState(false);
  const [denomination, setDenomination] = useState<Denomination>("neutral");
  const [sessionId] = useState(
    () =>
      globalThis.crypto?.randomUUID?.() ??
      `sess-${Math.random().toString(36).slice(2)}`,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Index of the assistant bubble currently being streamed into.
  const replyIdx = useRef<number>(-1);

  function updateReply(patch: (t: Turn) => Turn) {
    setTurns((prev) =>
      prev.map((t, i) => (i === replyIdx.current ? patch(t) : t)),
    );
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
            streaming: false,
          })),
        onError: (msg) => setError(msg),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
      updateReply((t) => ({ ...t, streaming: false }));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="shell">
      <h1>Christianity AI Assistant</h1>
      <p className="muted">
        Streaming chat with memory, denomination framing, and images
      </p>

      <div className="messages">
        {turns.map((turn, i) => (
          <div key={i} className={`bubble ${turn.role}`}>
            {turn.role === "assistant" && turn.intent ? (
              <span className="badge">{turn.intent.kind}</span>
            ) : null}
            {turn.content}
            {turn.streaming && !turn.content ? (
              <span className="muted">thinking...</span>
            ) : null}
            {turn.image ? (
              <img
                src={`data:image/png;base64,${turn.image}`}
                alt="generated"
              />
            ) : null}
          </div>
        ))}
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
  );
}
