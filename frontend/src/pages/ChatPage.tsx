import { useEffect, useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  conversationsApi,
  streamChat,
  type MessageItem,
  type SourceItem,
  type StreamHandlers,
  ApiError,
} from "@/lib/api";
import { ConversationList } from "@/components/chat/ConversationList";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { ChatInput } from "@/components/chat/ChatInput";

// 内部使用的会话信息（扩展自 API 类型）
interface ConvInfo {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

// 内部消息（扩展自 API 类型，添加流式来源）
interface Msg {
  id?: string;
  role: "user" | "assistant" | "tool";
  content: string;
  status: string;
  error: string | null;
  sources: SourceItem[];
}

export function ChatPage() {
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<ConvInfo[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingConv, setLoadingConv] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [retrieving, setRetrieving] = useState(false);
  void retrieving; // suppress unused warning
  const abortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // 检查登录状态
  useEffect(() => {
    loadConversations();
  }, []);

  const loadConversations = async () => {
    try {
      const data = await conversationsApi.list();
      setConversations(data.conversations as ConvInfo[]);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        navigate("/login");
        return;
      }
      console.error("加载会话列表失败:", err);
    } finally {
      setLoading(false);
    }
  };

  // 加载选中会话的消息
  const loadMessages = async (convId: string) => {
    setLoadingConv(true);
    try {
      const result = await conversationsApi.getMessages(convId);
      // 过滤掉 tool 角色的消息（它们是内部工具结果）
      const filtered = result.messages.filter(
        (m: MessageItem) => m.role !== "tool"
      ).map((m: MessageItem) => ({
        id: m.id,
        role: m.role as "user" | "assistant",
        content: m.content,
        status: m.status,
        error: m.error,
        sources: m.sources || [],
      }));
      setMessages(filtered);
    } catch (err) {
      console.error("加载消息失败:", err);
    } finally {
      setLoadingConv(false);
    }
  };

  const handleSelectConv = (id: string) => {
    setActiveConvId(id);
    loadMessages(id);
  };

  const handleCreateConv = async () => {
    try {
      const conv = await conversationsApi.create();
      setConversations((prev) => [conv as ConvInfo, ...prev]);
      setActiveConvId(conv.id);
      setMessages([]);
    } catch (err) {
      console.error("创建会话失败:", err);
    }
  };

  const handleRename = async (id: string, title: string) => {
    try {
      const updated = await conversationsApi.rename(id, title);
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? ({ ...c, title: updated.title } as ConvInfo) : c))
      );
    } catch (err) {
      console.error("重命名失败:", err);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await conversationsApi.remove(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeConvId === id) {
        setActiveConvId(null);
        setMessages([]);
      }
    } catch (err) {
      console.error("删除失败:", err);
    }
  };

  const handleSend = async (content: string) => {
    if (!activeConvId) return;

    const controller = new AbortController();
    abortRef.current = controller;

    // 立即显示用户消息
    const userMsg: Msg = {
      role: "user",
      content,
      status: "completed",
      error: null,
      sources: [],
    };
    const assistantMsg: Msg = {
      role: "assistant",
      content: "",
      status: "streaming",
      error: null,
      sources: [],
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setStreaming(true);
    setRetrieving(false);

    let accumulated = "";
    let hasSources = false;
    let currentSources: SourceItem[] = [];

    const handlers: StreamHandlers = {
      onStatus: (data) => {
        if (data.stage === "retrieving") {
          setRetrieving(true);
        } else if (data.stage === "thinking") {
          setRetrieving(false);
        }
      },
      onDelta: (data) => {
        accumulated += data.content;
        setMessages((prev) => {
          const copy = [...prev];
          const last = copy[copy.length - 1];
          if (last && last.role === "assistant") {
            copy[copy.length - 1] = { ...last, content: accumulated };
          }
          return copy;
        });
      },
      onToolCall: () => {
        setRetrieving(true);
      },
      onSources: (data) => {
        currentSources = data.sources;
        hasSources = true;
        setMessages((prev) => {
          const copy = [...prev];
          const last = copy[copy.length - 1];
          if (last && last.role === "assistant") {
            copy[copy.length - 1] = { ...last, sources: [...currentSources] };
          }
          return copy;
        });
      },
      onDone: (_data) => {
        setStreaming(false);
        setRetrieving(false);
        setMessages((prev) => {
          const copy = [...prev];
          const last = copy[copy.length - 1];
          if (last && last.role === "assistant") {
            copy[copy.length - 1] = {
              ...last,
              content: accumulated,
              status: "completed",
              sources: hasSources ? [...currentSources] : last.sources,
            };
          }
          return copy;
        });
        // 刷新会话列表（标题可能更新）
        loadConversations();
      },
      onError: (data) => {
        setStreaming(false);
        setRetrieving(false);
        setMessages((prev) => {
          const copy = [...prev];
          const last = copy[copy.length - 1];
          if (last && last.role === "assistant") {
            copy[copy.length - 1] = {
              ...last,
              content: accumulated || data.message,
              status: "failed",
              error: data.message,
            };
          }
          return copy;
        });
      },
    };

    try {
      await streamChat(activeConvId, content, handlers, controller.signal);
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        // 用户主动停止，保留已生成的内容
        setStreaming(false);
        setRetrieving(false);
        setMessages((prev) => {
          const copy = [...prev];
          const last = copy[copy.length - 1];
          if (last && last.role === "assistant") {
            copy[copy.length - 1] = {
              ...last,
              content: accumulated,
              status: accumulated ? "completed" : "error",
            };
          }
          return copy;
        });
      } else {
        handlers.onError?.({ message: (err as Error).message || "网络错误" });
      }
    } finally {
      abortRef.current = null;
    }
  };

  const handleStop = () => {
    abortRef.current?.abort();
  };

  return (
    <div className="h-screen flex bg-background">
      {/* 侧栏 */}
      <div className="w-64 shrink-0 h-full">
        <ConversationList
          conversations={conversations}
          activeId={activeConvId}
          onSelect={handleSelectConv}
          onCreate={handleCreateConv}
          onRename={handleRename}
          onDelete={handleDelete}
          loading={loading}
        />
      </div>

      {/* 主聊天区 */}
      <div className="flex-1 flex flex-col min-w-0 h-full">
        {!activeConvId ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            <div className="text-center">
              <h2 className="text-xl font-semibold mb-2">开始新对话</h2>
              <p className="text-sm">选择左侧会话或点击「新建对话」</p>
            </div>
          </div>
        ) : (
          <>
            {/* 消息区 */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {loadingConv ? (
                <p className="text-center text-sm text-muted-foreground py-8">
                  加载消息...
                </p>
              ) : messages.length === 0 ? (
                <div className="text-center text-muted-foreground py-8">
                  <p className="text-sm">开始你的第一条消息吧</p>
                </div>
              ) : (
                messages.map((msg, i) => (
                  <MessageBubble
                    key={msg.id || i}
                    role={msg.role}
                    content={msg.content}
                    status={msg.status}
                    error={msg.error}
                    sources={msg.sources}
                    isStreaming={streaming && i === messages.length - 1}
                  />
                ))
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* 输入区 */}
            <ChatInput
              onSend={handleSend}
              onStop={handleStop}
              disabled={false}
              streaming={streaming}
            />
          </>
        )}
      </div>
    </div>
  );
}
