import { AlertCircle } from "lucide-react";
import type { ReactNode } from "react";

export function QueryState({ isLoading, error, children }: { isLoading: boolean; error: Error | null; children: ReactNode }) {
  if (isLoading) {
    return (
      <div className="skeleton-stack" role="status" aria-label="Veriler yükleniyor">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-row" />
        <div className="skeleton skeleton-row" />
        <div className="skeleton skeleton-row" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="notice notice-bad" role="alert">
        <AlertCircle size={18} aria-hidden />
        <div><strong>Veri alınamadı</strong><p>{error.message}</p></div>
      </div>
    );
  }
  return <>{children}</>;
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}
