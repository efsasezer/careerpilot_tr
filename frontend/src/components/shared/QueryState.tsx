import { AlertCircle, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

export function QueryState({
  isLoading,
  error,
  children,
}: {
  isLoading: boolean;
  error: Error | null;
  children: ReactNode;
}) {
  if (isLoading) {
    return <div className="query-state"><LoaderCircle className="spin" size={19} /> Veriler yükleniyor…</div>;
  }
  if (error) {
    return (
      <div className="error-panel" role="alert">
        <AlertCircle size={20} />
        <div><strong>Veri alınamadı</strong><p>{error.message}</p></div>
      </div>
    );
  }
  return children;
}
