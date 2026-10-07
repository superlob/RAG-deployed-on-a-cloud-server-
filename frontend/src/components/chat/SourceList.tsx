import { Badge } from "@/components/ui/badge";
import { useState } from "react";
import { ChevronDown, ChevronUp, FileText } from "lucide-react";
import type { SourceItem } from "@/lib/api";

interface SourceListProps {
  sources: SourceItem[];
}

export function SourceList({ sources }: SourceListProps) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  const toggle = (idx: number) => {
    setExpanded((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-muted-foreground mb-1">
        参考来源 ({sources.length})
      </p>
      {sources.map((src, i) => (
        <SourceItemRow
          key={i}
          source={src}
          expanded={!!expanded[i]}
          onToggle={() => toggle(i)}
        />
      ))}
    </div>
  );
}

function SourceItemRow({ source, expanded, onToggle }: { source: SourceItem; expanded: boolean; onToggle: () => void }) {
  return (
    <div className="rounded-lg border border-border/50 overflow-hidden">
      <button
        className="w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-muted/50 transition-colors"
        onClick={onToggle}
      >
        <FileText className="size-3.5 text-muted-foreground shrink-0" />
        <Badge variant="secondary" className="shrink-0">
          {source.chunk_index + 1}
        </Badge>
        <span className="font-medium truncate">
          {source.document_title || "未知文档"}
        </span>
        <div className="ml-auto flex items-center gap-2 shrink-0">
          {source.page_number != null && (
            <span className="text-muted-foreground">
              第 {source.page_number} 页
            </span>
          )}
          {source.section_title && (
            <span className="text-muted-foreground">
              § {source.section_title}
            </span>
          )}
          {expanded ? (
            <ChevronUp className="size-3 text-muted-foreground" />
          ) : (
            <ChevronDown className="size-3 text-muted-foreground" />
          )}
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-2 text-xs text-muted-foreground whitespace-pre-wrap border-t border-border/50 pt-2">
          {source.snippet}
        </div>
      )}
    </div>
  );
}
