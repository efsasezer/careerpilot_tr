import { BellRing, CalendarClock, CheckCheck, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { useOpenJob } from "../components/jobs/JobCard";
import { PageHeader } from "../components/shared/PageHeader";
import { EmptyState, QueryState } from "../components/shared/QueryState";
import { useHealth, useNotifications, useReadAllNotifications, useReadNotification } from "../services/api/hooks";
import { formatTimestamp } from "../utils/format";

export default function NotificationsPage() {
  const query = useNotifications();
  const health = useHealth();
  const read = useReadNotification();
  const readAll = useReadAllNotifications();
  const open = useOpenJob();
  const readOnly = health.data?.read_only ?? true;
  const items = query.data?.items ?? [];

  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      <PageHeader
        title="Bildirimler"
        description="Profilinize uyan yeni ilanlar ve son başvurusu yaklaşan ilanlar burada birikir."
        action={
          <>
            <Link to="/settings" className="button"><BellRing size={16} /> Bildirim ayarları</Link>
            {(query.data?.unread ?? 0) > 0 && !readOnly && (
              <button className="button" onClick={() => readAll.mutate()} disabled={readAll.isPending}><CheckCheck size={16} /> Tümünü okundu say</button>
            )}
          </>
        }
      />
      {items.length ? (
        <ul className="notification-list">
          {items.map((item) => {
            const Icon = item.kind === "deadline" ? CalendarClock : Sparkles;
            return (
              <li key={item.id}>
                <button
                  className={`notification ${item.read ? "" : "notification-unread"}`}
                  onClick={() => {
                    if (!item.read && !readOnly) read.mutate(item.id);
                    if (item.job_id) open(item.job_id);
                  }}
                >
                  <span className={`notification-icon ${item.kind === "deadline" ? "notification-icon-deadline" : ""}`}><Icon size={17} aria-hidden /></span>
                  <span className="notification-main">
                    <strong>{item.title}</strong>
                    <span>{item.body}</span>
                    <time>{formatTimestamp(item.created_at)}</time>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <EmptyState title="Henüz bildirim yok">Kaynaklar tarandığında profilinize uyan yeni ilanlar için burada bildirim oluşur.</EmptyState>
      )}
    </QueryState>
  );
}
