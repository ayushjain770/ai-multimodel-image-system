export type Role = "user" | "assistant";

export type Denomination = "neutral" | "catholic" | "protestant" | "orthodox";

export interface ChatMessage {
  role: Role;
  content: string;
}

export interface IntentInfo {
  kind: "normal" | "scripture" | "image";
  needs_rag: boolean;
  tool: string | null;
  source: string;
}

export interface Citation {
  ref: string;
  translation: string;
  text: string;
}

export interface VerificationItem {
  ref: string;
  status: string;
  message: string;
}

export interface StreamMeta {
  intent: IntentInfo | null;
  citations: Citation[];
  session_id: string | null;
  backend: { llm: string; image: string };
}

export interface StreamFinal {
  reply: string;
  refused: boolean;
  moderated: boolean;
  moderation: { stage: string; category: string | null; reason: string | null } | null;
  verification: VerificationItem[];
  image_base64: string | null;
  image_url: string | null;
}

export interface StreamHandlers {
  onMeta?: (meta: StreamMeta) => void;
  onToken?: (delta: string) => void;
  onFinal?: (final: StreamFinal) => void;
  onError?: (message: string) => void;
}

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

/** Resolve a relative media URL (e.g. /media/x.png) against the API base. */
export function mediaUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.startsWith("http") ? url : `${API_URL}${url}`;
}

export async function streamChat(
  message: string,
  history: ChatMessage[],
  generateImage: boolean,
  sessionId: string,
  denomination: Denomination,
  handlers: StreamHandlers,
): Promise<void> {
  const res = await fetch(`${API_URL}/api/v1/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      history,
      session_id: sessionId,
      denomination,
      generate_image: generateImage,
    }),
  });

  if (!res.ok || !res.body) {
    throw new Error(`Gateway returned ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // SSE frames are separated by a blank line; each frame has event:/data: lines.
  const dispatch = (frame: string) => {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) return;
    const data = JSON.parse(dataLines.join("\n"));
    if (event === "meta") handlers.onMeta?.(data as StreamMeta);
    else if (event === "token") handlers.onToken?.((data as { delta: string }).delta);
    else if (event === "final") handlers.onFinal?.(data as StreamFinal);
    else if (event === "error") handlers.onError?.((data as { message: string }).message);
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      if (frame.trim()) dispatch(frame);
    }
  }
  if (buffer.trim()) dispatch(buffer);
}
