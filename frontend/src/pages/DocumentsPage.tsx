import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Upload,
  Trash2,
  Download,
  FileText,
  Loader2,
  Sparkles,
  ListTree,
  AlertCircle,
} from "lucide-react";
import {
  authApi,
  documentsApi,
  ApiError,
  type DocumentInfo,
  type ChunkItem,
  type User,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** 格式化文件大小 */
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

/** 文件类型对应的 Badge 样式 */
function fileTypeBadge(fileType: string) {
  const map: Record<string, string> = {
    pdf: "bg-red-100 text-red-800 border-red-200",
    doc: "bg-blue-100 text-blue-800 border-blue-200",
    docx: "bg-blue-100 text-blue-800 border-blue-200",
  };
  return (
    <Badge variant="outline" className={map[fileType] ?? "bg-gray-100 text-gray-800 border-gray-200"}>
      {fileType.toUpperCase()}
    </Badge>
  );
}

/** 处理状态对应的 Badge */
function statusBadge(status: string, error?: string | null) {
  const cfg = getStatusCodeConfig(status);
  return (
    <Badge
      variant="outline"
      className={`inline-flex items-center gap-1 ${cfg.className}`}
      title={status === "failed" && error ? error : undefined}
    >
      {cfg.icon}
      {cfg.label}
    </Badge>
  );
}

function getStatusCodeConfig(status: string) {
  const map: Record<string, { label: string; className: string; icon?: React.ReactNode }> = {
    not_processed: {
      label: "未处理",
      className: "bg-gray-100 text-gray-800 border-gray-200",
    },
    processing: {
      label: "处理中",
      className: "bg-yellow-100 text-yellow-800 border-yellow-200",
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
    },
    embedded: {
      label: "已嵌入",
      className: "bg-green-100 text-green-800 border-green-200",
    },
    failed: {
      label: "失败",
      className: "bg-red-100 text-red-800 border-red-200",
      icon: <AlertCircle className="h-3 w-3" />,
    },
  };
  return map[status] ?? map.not_processed;
}

export function DocumentsPage() {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [fetchingDocs, setFetchingDocs] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<DocumentInfo | null>(null);
  const [deleting, setDeleting] = useState(false);
  /** 正在触发处理的文档 ID 集合（用于防止重复点击） */
  const [processingIds, setProcessingIds] = useState<Set<string>>(new Set());
  /** 查看分块的文档 */
  const [chunkTarget, setChunkTarget] = useState<DocumentInfo | null>(null);
  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [loadingChunks, setLoadingChunks] = useState(false);
  const [chunkError, setChunkError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  /** 认证检查 + 加载文档列表 */
  useEffect(() => {
    checkAuth();
  }, []);

  useEffect(() => {
    if (user) {
      fetchDocuments();
    }
  }, [user]);

  /** 轮询：有文档处于 processing 状态时每 3 秒刷新列表 */
  useEffect(() => {
    const hasProcessing = documents.some(
      (d) => d.processing_status === "processing"
    );
    if (!hasProcessing) return;

    const timer = setInterval(() => {
      fetchDocuments();
    }, 3000);

    return () => clearInterval(timer);
  }, [documents]);

  const checkAuth = async () => {
    try {
      const userData = await authApi.me();
      setUser(userData);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) {
        navigate("/login");
      } else {
        setError("获取用户信息失败");
      }
    } finally {
      setLoading(false);
    }
  };

  /** 加载文档列表 */
  const fetchDocuments = async () => {
    setFetchingDocs(true);
    try {
      const data = await documentsApi.list();
      setDocuments(data.documents);
      // 调试日志：打印第一条文档的字段
      if (data.documents.length > 0) {
        console.log("[debug] 文档字段:", Object.keys(data.documents[0]));
      }
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) {
        navigate("/login");
      } else {
        setError("加载文档列表失败");
      }
    } finally {
      setFetchingDocs(false);
    }
  };

  /** 上传文件 */
  const uploadFiles = async (files: FileList | File[]) => {
    setUploading(true);
    setError("");
    let hasError = false;

    for (const file of Array.from(files)) {
      try {
        await documentsApi.upload(file);
      } catch (err: unknown) {
        if (err instanceof ApiError) {
          setError(`${file.name}: ${err.message}`);
        } else {
          setError(`${file.name}: 上传失败`);
        }
        hasError = true;
      }
    }

    if (!hasError) {
      setError("");
    }
    setUploading(false);
    await fetchDocuments();
  };

  /** 拖拽事件处理 */
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      uploadFiles(e.dataTransfer.files);
    }
  }, []);

  /** 文件选择器事件 */
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      uploadFiles(e.target.files);
      e.target.value = "";
    }
  };

  /** 触发向量化处理 */
  const handleProcess = async (doc: DocumentInfo) => {
    setError("");
    // 乐观更新：立即显示处理中
    setDocuments((prev) =>
      prev.map((d) =>
        d.id === doc.id
          ? { ...d, processing_status: "processing", status_error: null }
          : d
      )
    );
    setProcessingIds((prev) => new Set(prev).add(doc.id));

    try {
      await documentsApi.process(doc.id);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(`启动处理失败: ${err.message}`);
      } else {
        setError("启动处理失败");
      }
      // 回滚状态
      await fetchDocuments();
    } finally {
      setProcessingIds((prev) => {
        const next = new Set(prev);
        next.delete(doc.id);
        return next;
      });
    }
  };

  /** 查看分块 */
  const handleViewChunks = async (doc: DocumentInfo) => {
    setChunkTarget(doc);
    setChunks([]);
    setChunkError("");
    setLoadingChunks(true);
    try {
      const data = await documentsApi.getChunks(doc.id);
      setChunks(data.chunks);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setChunkError(err.message);
      } else {
        setChunkError("加载分块失败");
      }
    } finally {
      setLoadingChunks(false);
    }
  };

  /** 删除文档 */
  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await documentsApi.delete(deleteTarget.id);
      setDocuments((prev) => prev.filter((d) => d.id !== deleteTarget.id));
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(`删除失败: ${err.message}`);
      } else {
        setError("删除失败");
      }
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <p className="text-muted-foreground">加载中...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-background">
      {/* 顶部导航 */}
      <header className="border-b border-border">
        <div className="container mx-auto px-4 py-4 flex justify-between items-center">
          <h1 className="text-xl font-bold">
            <Link to="/">RAG 应用</Link>
          </h1>
          <div className="flex items-center gap-4">
            <span className="text-sm text-muted-foreground">
              欢迎, {user?.username}
            </span>
          </div>
        </div>
      </header>

      {/* 主内容区 */}
      <main className="flex-1 container mx-auto px-4 py-8">
        {error && (
          <div className="mb-4 p-3 text-sm text-destructive bg-destructive/10 rounded-md">
            {error}
          </div>
        )}

        {/* 上传区域 */}
        <Card className="mb-8">
          <CardHeader>
            <CardTitle>上传文档</CardTitle>
            <CardDescription>
              支持 PDF、DOC、DOCX 格式，最大 50MB
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div
              onDragOver={handleDragOver}
              onDragEnter={handleDragEnter}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`
                border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors
                ${dragActive
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50 hover:bg-muted/50"
                }
              `}
            >
              {uploading ? (
                <div className="flex flex-col items-center gap-2">
                  <Loader2 className="h-8 w-8 animate-spin text-primary" />
                  <p className="text-muted-foreground">上传中...</p>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2">
                  <Upload className="h-8 w-8 text-muted-foreground" />
                  <p className="font-medium">拖拽文件到此处，或点击选择文件</p>
                  <p className="text-sm text-muted-foreground">
                    PDF · DOC · DOCX
                  </p>
                </div>
              )}
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.doc,.docx"
                className="hidden"
                onChange={handleFileSelect}
              />
            </div>
          </CardContent>
        </Card>

        {/* 文档列表 */}
        <Card>
          <CardHeader>
            <CardTitle>我的文档</CardTitle>
            <CardDescription>
              {documents.length > 0
                ? `共 ${documents.length} 个文档`
                : "暂无文档"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {fetchingDocs && documents.length === 0 ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : documents.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
                <FileText className="h-10 w-10" />
                <p>还没有上传任何文档</p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>文件名</TableHead>
                    <TableHead>类型</TableHead>
                    <TableHead>大小</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>上传时间</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {documents.map((doc) => (
                    <TableRow key={doc.id}>
                      <TableCell className="font-medium max-w-[240px] truncate">
                        {doc.original_filename}
                      </TableCell>
                      <TableCell>{fileTypeBadge(doc.file_type)}</TableCell>
                      <TableCell>{formatFileSize(doc.file_size)}</TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          {statusBadge(doc.processing_status, doc.status_error)}
                          {doc.processing_status === "embedded" &&
                            doc.chunk_count > 0 && (
                              <span className="text-xs text-muted-foreground">
                                {doc.chunk_count} 块
                              </span>
                            )}
                        </div>
                      </TableCell>
                      <TableCell>
                        {new Date(doc.created_at).toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          {/* 已嵌入 → 可看分块 */}
                          {doc.processing_status === "embedded" && (
                            <Button
                              variant="ghost"
                              size="icon"
                              title="查看分块"
                              onClick={() => handleViewChunks(doc)}
                            >
                              <ListTree className="h-4 w-4 text-primary" />
                            </Button>
                          )}
                          {/* 向量化按钮 */}
                          <Button
                            variant="ghost"
                            size="icon"
                            title={
                              doc.processing_status === "processing"
                                ? "处理中..."
                                : doc.processing_status === "not_processed"
                                  ? "向量化"
                                  : "重新向量化"
                            }
                            disabled={
                              doc.processing_status === "processing" ||
                              processingIds.has(doc.id)
                            }
                            onClick={() => handleProcess(doc)}
                          >
                            <Sparkles
                              className={`h-4 w-4 ${
                                doc.processing_status === "processing"
                                  ? "text-yellow-500"
                                  : "text-purple-500"
                              }`}
                            />
                          </Button>
                          {/* 下载 */}
                          <Button
                            variant="ghost"
                            size="icon"
                            asChild
                            title="下载"
                          >
                            <a
                              href={documentsApi.getDownloadUrl(doc.id)}
                              download
                            >
                              <Download className="h-4 w-4" />
                            </a>
                          </Button>
                          {/* 删除 */}
                          <Button
                            variant="ghost"
                            size="icon"
                            title="删除"
                            onClick={() => setDeleteTarget(doc)}
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </main>

      {/* 删除确认对话框 */}
      <Dialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              确定要删除文件{" "}
              <strong>{deleteTarget?.original_filename}</strong> 吗？
              此操作不可撤销，同时会删除所有已生成的分块和向量。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteTarget(null)}
              disabled={deleting}
            >
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={confirmDelete}
              disabled={deleting}
            >
              {deleting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  删除中...
                </>
              ) : (
                "删除"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 分块查看对话框 */}
      <Dialog
        open={!!chunkTarget}
        onOpenChange={(open) => !open && setChunkTarget(null)}
      >
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>{chunkTarget?.original_filename}</DialogTitle>
            <DialogDescription>
              共 {chunks.length} 个分块
              {chunkTarget?.embedded_at &&
                ` · 嵌入于 ${new Date(chunkTarget.embedded_at).toLocaleString()}`}
            </DialogDescription>
          </DialogHeader>

          <div className="flex-1 overflow-y-auto space-y-3 pr-2">
            {loadingChunks ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : chunkError ? (
              <div className="p-3 text-sm text-destructive bg-destructive/10 rounded-md">
                {chunkError}
              </div>
            ) : chunks.length === 0 ? (
              <p className="text-center py-8 text-muted-foreground">暂无分块</p>
            ) : (
              chunks.map((chunk) => (
                <div
                  key={chunk.id}
                  className="border border-border rounded-md p-3 text-sm"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">#{chunk.chunk_index}</Badge>
                      {chunk.section_title && (
                        <span className="font-medium text-foreground">
                          {chunk.section_title}
                        </span>
                      )}
                      {chunk.page_number != null && (
                        <span className="text-xs text-muted-foreground">
                          第 {chunk.page_number} 页
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {chunk.content_length} 字符
                    </span>
                  </div>
                  <p className="text-muted-foreground whitespace-pre-wrap break-words">
                    {chunk.content_preview}
                    {chunk.content_length > chunk.content_preview.length && "…"}
                  </p>
                </div>
              ))
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setChunkTarget(null)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
