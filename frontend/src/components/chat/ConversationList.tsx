import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { Plus, Edit, Trash2, MessageSquare } from "lucide-react";
import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export interface ConversationInfo {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

interface ConversationListProps {
  conversations: ConversationInfo[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  loading?: boolean;
}

export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onCreate,
  onRename,
  onDelete,
  loading,
}: ConversationListProps) {
  return (
    <div className="flex flex-col h-full bg-card border-r border-border">
      <div className="p-3 border-b border-border">
        <Button
          variant="outline"
          className="w-full gap-2"
          onClick={onCreate}
        >
          <Plus className="size-4" />
          新建对话
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <p className="p-3 text-sm text-muted-foreground">加载中...</p>
        ) : conversations.length === 0 ? (
          <div className="p-6 text-center text-muted-foreground text-sm">
            <MessageSquare className="size-8 mx-auto mb-2 opacity-40" />
            <p>暂无对话</p>
            <p className="text-xs mt-1">点击上方按钮开始新的对话</p>
          </div>
        ) : (
          conversations.map((conv) => (
            <ConversationItem
              key={conv.id}
              conv={conv}
              isActive={conv.id === activeId}
              onSelect={() => onSelect(conv.id)}
              onRename={onRename}
              onDelete={onDelete}
            />
          ))
        )}
      </div>
    </div>
  );
}

interface ConversationItemProps {
  conv: ConversationInfo;
  isActive: boolean;
  onSelect: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}

function ConversationItem({
  conv,
  isActive,
  onSelect,
  onRename,
  onDelete,
}: ConversationItemProps) {
  const [hovered, setHovered] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(conv.title);
  const [showDelete, setShowDelete] = useState(false);

  const handleRename = () => {
    const trimmed = title.trim();
    if (trimmed && trimmed !== conv.title) {
      onRename(conv.id, trimmed);
    }
    setRenaming(false);
  };

  return (
    <>
      <div
        className={cn(
          "group relative flex items-center gap-2 px-3 py-2.5 cursor-pointer text-sm border-b border-border/50 transition-colors",
          isActive
            ? "bg-accent text-accent-foreground font-medium"
            : "hover:bg-muted/50"
        )}
        onClick={onSelect}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        <MessageSquare
          className={cn(
            "size-4 shrink-0",
            isActive ? "text-primary" : "text-muted-foreground"
          )}
        />
        <div className="flex-1 min-w-0 truncate">{conv.title}</div>

        {hovered && (
          <div className="shrink-0 flex gap-1">
            <button
              className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
              onClick={(e) => {
                e.stopPropagation();
                setTitle(conv.title);
                setRenaming(true);
              }}
            >
              <Edit className="size-3.5" />
            </button>
            <button
              className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
              onClick={(e) => {
                e.stopPropagation();
                setShowDelete(true);
              }}
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
        )}
      </div>

      {/* Rename Dialog */}
      {renaming && (
        <Dialog open={renaming} onOpenChange={(v) => !v && setRenaming(false)}>
          <DialogContent className="sm:max-w-sm">
            <DialogHeader>
              <DialogTitle>重命名对话</DialogTitle>
            </DialogHeader>
            <div className="flex gap-2 mt-4">
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleRename()}
                autoFocus
              />
              <Button onClick={handleRename}>确认</Button>
            </div>
          </DialogContent>
        </Dialog>
      )}

      {/* Delete Confirmation */}
      {showDelete && (
        <Dialog open={showDelete} onOpenChange={(v) => !v && setShowDelete(false)}>
          <DialogContent className="sm:max-w-sm">
            <DialogHeader>
              <DialogTitle>删除对话</DialogTitle>
            </DialogHeader>
            <p className="text-sm text-muted-foreground mt-2">
              确定要删除「{conv.title}」吗？此操作不可撤销。
            </p>
            <div className="flex gap-2 mt-4 justify-end">
              <Button variant="outline" onClick={() => setShowDelete(false)}>
                取消
              </Button>
              <Button
                variant="destructive"
                onClick={() => {
                  onDelete(conv.id);
                  setShowDelete(false);
                }}
              >
                删除
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
