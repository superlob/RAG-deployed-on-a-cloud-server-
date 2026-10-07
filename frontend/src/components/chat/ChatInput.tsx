import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Send, Square } from "lucide-react";
import { useState, useRef, useEffect, type KeyboardEvent, type ChangeEvent } from "react";

interface ChatInputProps {
  onSend: (content: string) => void;
  onStop: () => void;
  disabled?: boolean;
  streaming?: boolean;
  placeholder?: string;
}

export function ChatInput({
  onSend,
  onStop,
  disabled,
  streaming,
  placeholder = "输入你的问题...",
}: ChatInputProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isSending = streaming;

  // 自动调整 textarea 高度
  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = "auto";
      ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
    }
  }, [text]);

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed || isSending) return;
    onSend(trimmed);
    setText("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
  };

  return (
    <div className="border-t border-border bg-card p-3">
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        <textarea
          ref={textareaRef}
          className={cn(
            "flex-1 resize-none rounded-xl border border-input bg-background px-4 py-2.5 text-sm",
            "focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary",
            "placeholder:text-muted-foreground",
            "min-h-[44px] max-h-[160px] leading-relaxed",
            "scrollbar-thin"
          )}
          value={text}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
        />
        {isSending ? (
          <Button
            variant="destructive"
            size="icon"
            className="shrink-0 h-11 w-11 rounded-xl"
            onClick={onStop}
          >
            <Square className="size-4" />
          </Button>
        ) : (
          <Button
            size="icon"
            className="shrink-0 h-11 w-11 rounded-xl"
            disabled={disabled || !text.trim()}
            onClick={handleSend}
          >
            <Send className="size-4" />
          </Button>
        )}
      </div>
      <p className="text-center text-[10px] text-muted-foreground mt-1.5">
        按 Enter 发送，Shift + Enter 换行
      </p>
    </div>
  );
}
