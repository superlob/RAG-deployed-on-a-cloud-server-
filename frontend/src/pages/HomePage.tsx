import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { authApi, type User } from "@/lib/api";

export function HomePage() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    checkAuth();
  }, []);

  const checkAuth = async () => {
    try {
      const userData = await authApi.me();
      setUser(userData);
    } catch (err: any) {
      // 不依赖 instanceof，直接检查 status 属性
      if (err?.status === 401) {
        setUser(null);
      } else {
        setError("获取用户信息失败");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await authApi.logout();
      setUser(null);
    } catch (err) {
      setError("登出失败");
    } finally {
      setLoggingOut(false);
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
      <header className="border-b border-border">
        <div className="container mx-auto px-4 py-4 flex justify-between items-center">
          <h1 className="text-xl font-bold">RAG 应用</h1>
          {user && (
            <div className="flex items-center gap-4">
              <span className="text-sm text-muted-foreground">
                欢迎, {user.username}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={handleLogout}
                disabled={loggingOut}
              >
                {loggingOut ? "登出中..." : "登出"}
              </Button>
            </div>
          )}
        </div>
      </header>

      <main className="flex-1 container mx-auto px-4 py-8">
        {error && (
          <div className="mb-4 p-3 text-sm text-destructive bg-destructive/10 rounded-md">
            {error}
          </div>
        )}

        {user ? (
          <div className="space-y-4">
            <h2 className="text-2xl font-semibold">欢迎回来！</h2>
            <div className="p-4 bg-card rounded-lg border border-border space-y-2">
              <p>
                <span className="font-medium">用户 ID:</span> {user.id}
              </p>
              <p>
                <span className="font-medium">用户名:</span> {user.username}
              </p>
              <p>
                <span className="font-medium">注册时间:</span>{" "}
                {new Date(user.created_at).toLocaleString()}
              </p>
            </div>
            <div className="pt-4 flex flex-wrap gap-3">
              <Button asChild>
                <Link to="/documents">文档管理</Link>
              </Button>
              <Button asChild variant="secondary">
                <Link to="/chat">AI 对话</Link>
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <h2 className="text-2xl font-semibold">请先登录</h2>
            <p className="text-muted-foreground">
              您需要登录才能访问完整功能
            </p>
            <div className="flex gap-4">
              <Button asChild>
                <Link to="/login">登录</Link>
              </Button>
              <Button variant="outline" asChild>
                <Link to="/register">注册</Link>
              </Button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
