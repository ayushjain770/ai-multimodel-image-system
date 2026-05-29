export type Role = "user" | "assistant";

export type Denomination = "neutral" | "catholic" | "protestant" | "orthodox";

export interface ChatMessage {
  role: Role;
  content: string;
}

export interface ChatResponse {
  reply: string;
  image_base64: string | null;
  session_id: string | null;
  backend: { llm: string; image: string };
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

export async function sendChat(
  message: string,
  history: ChatMessage[],
  generateImage: boolean,
  sessionId: string,
  denomination: Denomination = "neutral",
): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/api/v1/chat`, {
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

  if (!res.ok) {
    throw new Error(`Gateway returned ${res.status}`);
  }
  return (await res.json()) as ChatResponse;
}
