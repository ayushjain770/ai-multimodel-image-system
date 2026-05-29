"use client";

import { useState } from "react";
import { sendChat, type ChatMessage, type Denomination } from "@/lib/api";

interface Turn extends ChatMessage {
  image?: string | null;
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
    setTurns((t) => [...t, { role: "user", content: message }]);
    setInput("");

    try {
      const res = await sendChat(
        message,
        history,
        generateImage,
        sessionId,
        denomination,
      );
      setTurns((t) => [
        ...t,
        { role: "assistant", content: res.reply, image: res.image_base64 },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="shell">
      <h1>Christianity AI Assistant</h1>
      <p className="muted">Grounded chat with memory, denomination framing, and images</p>

      <div className="messages">
        {turns.map((turn, i) => (
          <div key={i} className={`bubble ${turn.role}`}>
            {turn.content}
            {turn.image ? (
              <img
                src={`data:image/png;base64,${turn.image}`}
                alt="generated"
              />
            ) : null}
          </div>
        ))}
        {loading ? <div className="bubble assistant muted">thinking...</div> : null}
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
