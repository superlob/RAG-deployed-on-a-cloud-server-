// 使用相对路径，通过 Vite proxy 转发到后端
const API_BASE_URL = "";

interface User {
  id: string;
  username: string;
  created_at: string;
}

interface LoginResponse {
  user: User;
}

interface RegisterResponse extends User {}

export interface DocumentInfo {
  id: string;
  original_filename: string;
  file_type: string;
  file_size: number;
  created_at: string;
  processing_status: string;
  status_error: string | null;
  chunk_count: number;
  embedded_at: string | null;
}

interface DocumentListResponse {
  documents: DocumentInfo[];
  total: number;
}

export interface DocumentStatusResponse {
  document_id: string;
  processing_status: string;
  status_error: string | null;
  chunk_count: number;
  embedded_at: string | null;
}

export interface ChunkItem {
  id: string;
  chunk_index: number;
  content_preview: string;
  content_length: number;
  section_title: string | null;
  page_number: number | null;
}

interface ChunkListResponse {
  document_id: string;
  chunks: ChunkItem[];
  total: number;
}

// Chat API types
export interface ConversationInfo {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationListResponse {
  conversations: ConversationInfo[];
  total: number;
}

export interface ConversationCreate {
  title?: string;
}

export interface SourceItem {
  document_id: string;
  document_title: string;
  chunk_index: number;
  section_title: string | null;
  page_number: number | null;
  snippet: string;
  score: number;
}

export interface MessageItem {
  id: string;
  turn_index: number;
  seq: number;
  role: "user" | "assistant" | "tool";
  content: string;
  tool_calls: unknown;
  tool_name: string | null;
  sources: SourceItem[];
  status: string;
  error: string | null;
  created_at: string;
}

export interface MessageListResponse {
  messages: MessageItem[];
  total: number;
}

export interface StreamHandlers {
  onStatus?: (data: { stage: string; model?: string }) => void;
  onDelta?: (data: { content: string }) => void;
  onToolCall?: (data: {
    id: string;
    name: string;
    arguments: string;
    query?: string;
    results_count?: number;
  }) => void;
  onSources?: (data: { sources: SourceItem[] }) => void;
  onDone?: (data: {
    message_id: string;
    conversation_id: string;
    included_turns: number;
    dropped_turns: number;
  }) => void;
  onError?: (data: { message: string }) => void;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

  const response = await fetch(url, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new ApiError(response.status, errorData.detail || "请求失败");
  }

  return response.json();
}

export const authApi = {
  register: (username: string, password: string) =>
    fetchApi<RegisterResponse>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  login: (username: string, password: string) =>
    fetchApi<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  logout: () =>
    fetchApi<{ message: string }>("/api/v1/auth/logout", {
      method: "POST",
    }),

  refresh: () =>
    fetchApi<{ message: string }>("/api/v1/auth/refresh", {
      method: "POST",
    }),

  me: () => fetchApi<User>("/api/v1/auth/me"),
};

export const documentsApi = {
  /**
   * 上传文档（PDF / Word）
   * 单独使用 fetch（不使用 fetchApi）以避免强制设置 Content-Type: application/json，
   * 文件上传需要浏览器自动设置 multipart/form-data boundary
   */
  async upload(file: File): Promise<DocumentInfo> {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/v1/documents/upload", {
      method: "POST",
      credentials: "include",
      body: formData,
    });
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new ApiError(res.status, errorData.detail || "上传失败");
    }
    return res.json();
  },

  list: () => fetchApi<DocumentListResponse>("/api/v1/documents/"),

  delete: (id: string) =>
    fetchApi<void>(`/api/v1/documents/${id}`, {
      method: "DELETE",
    }),

  /**
   * 获取下载链接（用于 <a> 标签触发下载）
   * 注意：后端需要 cookie 认证，直接用 href 会带上 cookie（credentials: include）
   */
  getDownloadUrl(id: string): string {
    return `/api/v1/documents/${id}`;
  },

  process: (
    id: string,
    options?: { chunk_size?: number; chunk_overlap?: number }
  ) =>
    fetchApi<{ message: string; document_id: string; status: string }>(
      `/api/v1/documents/${id}/process`,
      {
        method: "POST",
        body: JSON.stringify(options ?? {}),
      }
    ),

  getStatus: (id: string) =>
    fetchApi<DocumentStatusResponse>(`/api/v1/documents/${id}/status`),

  getChunks: (id: string) =>
    fetchApi<ChunkListResponse>(`/api/v1/documents/${id}/chunks`),
};

export const conversationsApi = {
  list: () => fetchApi<ConversationListResponse>("/api/v1/conversations"),

  create: (title?: string) =>
    fetchApi<ConversationInfo>("/api/v1/conversations", {
      method: "POST",
      body: JSON.stringify(title ? { title } : {}),
    }),

  rename: (id: string, title: string) =>
    fetchApi<ConversationInfo>(`/api/v1/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  remove: (id: string) =>
    fetchApi<void>(`/api/v1/conversations/${id}`, {
      method: "DELETE",
    }),

  getMessages: (id: string) =>
    fetchApi<MessageListResponse>(`/api/v1/conversations/${id}/messages`),
};

/**
 * SSE 流式发送消息
 *
 * 手动解析 text/event-stream（EventSource 不支持 POST + cookie 场景）。
 */
export async function streamChat(
  conversationId: string,
  content: string,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch(
    `/api/v1/conversations/${conversationId}/messages`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
      signal,
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new ApiError(response.status, errorData.detail || "发送失败");
  }

  if (!response.body) {
    throw new ApiError(500, "响应体为空");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        if (!part.trim() || part.startsWith(":")) continue;
        parseEvent(part, handlers);
      }
    }

    if (buffer.trim() && !buffer.startsWith(":")) {
      parseEvent(buffer, handlers);
    }
  } finally {
    reader.releaseLock();
  }
}

function parseEvent(raw: string, handlers: StreamHandlers) {
  const lines = raw.split("\n");
  let eventName: string | null = null;
  let dataStr = "";

  for (const line of lines) {
    if (line.startsWith("event: ")) {
      eventName = line.slice(7);
    } else if (line.startsWith("data: ")) {
      dataStr += (dataStr ? "\n" : "") + line.slice(6);
    }
  }

  if (!eventName || !dataStr) return;

  const data = (() => {
    try {
      return JSON.parse(dataStr);
    } catch {
      return { message: dataStr };
    }
  })();

  switch (eventName) {
    case "status":
      handlers.onStatus?.(data);
      break;
    case "delta":
      handlers.onDelta?.(data);
      break;
    case "tool_call":
      handlers.onToolCall?.(data);
      break;
    case "sources":
      handlers.onSources?.(data);
      break;
    case "done":
      handlers.onDone?.(data);
      break;
    case "error":
      handlers.onError?.(data);
      break;
  }
}

export type { User, LoginResponse, RegisterResponse };
