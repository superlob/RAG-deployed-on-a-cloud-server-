import { cn } from "@/lib/utils";
import { Loader2, AlertCircle } from "lucide-react";
import type { SourceItem } from "@/lib/api";
import { SourceList } from "./SourceList";

export interface MessageBubbleProps {
  role: "user" | "assistant" | "tool";
  content: string;
  status?: string;
  error?: string | null;
  sources?: SourceItem[];
  isStreaming?: boolean;
}

export function MessageBubble({
  role,
  content,
  status = "completed",
  error,
  sources,
  isStreaming,
}: MessageBubbleProps) {
  const isUser = role === "user";
  const isError = status === "failed" || status === "error";
  const isRetrieving = status === "streaming" && isStreaming;

  return (
    <div
      className={cn(
        "flex w-full",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap break-words",
          isUser
            ? "bg-primary text-primary-foreground rounded-br-sm"
            : "bg-muted/80 text-foreground rounded-bl-sm"
        )}
      >
        {/* 流式输出时的光标 */}
        {isStreaming && content && (
          <span className="inline-block w-0.5 h-4 bg-foreground animate-pulse ml-0.5 align-text-bottom" />
        )}

        {/* 工具调用中的状态提示 */}
        {isRetrieving && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground mb-2">
            <Loader2 className="size-3 animate-spin" />
            正在检索文档…
          </div>
        )}

        {/* 内容 */}
        {content && <div>{content}</div>}

        {/* 错误提示 */}
        {isError && error && (
          <div className="flex items-center gap-1.5 mt-2 text-xs text-destructive">
            <AlertCircle className="size-3" />
            {error}
          </div>
        )}

        {/* 来源卡片 */}
        {sources && sources.length > 0 && (
          <div className="mt-3 border-t border-border/50 pt-2">
            <SourceList sources={sources} />
          </div>
        )}
      </div>
    </div>
  );
}
