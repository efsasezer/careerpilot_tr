import { BellRing, CalendarClock, CheckCheck, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { useOpenJob } from "../components/jobs/JobCard";
import { PageHeader } from "../components/shared/PageHeader";
import { EmptyState, QueryState } from "../components/shared/QueryState";
import { useNotifications, useReadAllNotifications, useReadNotification } from "../services/api/hooks";
import { formatTimestamp } from "../utils/format";

export default function NotificationsPage() {
  const query = useNotifications();
  const read = useReadNotification();
  const readAll = useReadAllNotifications();
  const open = useOpenJob();
  const items = query.data?.items ?? [];

  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      <PageHeader
        title="Bildirimler"
        description="Yaklaşan başvurular, son tarihler, sınav ve mülakatlar, bugünkü görevleriniz ve güncellenen ilanlar."
        action={
          <>
            <Link to="/settings" className="button"><BellRing size={16} /> Bildirim ayarları</Link>
            {(query.data?.unread ?? 0) > 0 && (
              <button className="button" onClick={() => readAll.mutate()} disabled={readAll.isPending}><CheckCheck size={16} /> Tümünü okundu say</button>
            )}
          </>
        }
      />
      {items.length ? (
        <ul className="notification-list">
          {items.map((item) => {
            const Icon = item.kind === "new_match" ? Sparkles : CalendarClock;
            return (
              <li key={item.id}>
                <button
                  className={`notification ${item.read ? "" : "notification-unread"}`}
                  onClick={() => {
                    if (!item.read) read.mutate(item.id);
                    if (item.job_id) open(item.job_id);
                  }}
                >
                  <span className={`notification-icon ${item.kind === "new_match" ? "" : "notification-icon-deadline"}`}><Icon size={17} aria-hidden /></span>
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
        <EmptyState title="Henüz bildirim yok">Bildirimler siteyi açtığınızda hesaplanır: yaklaşan son tarihler, etkinlikler ve bugünkü görevleriniz burada görünür.</EmptyState>
      )}
    </QueryState>
  );
}
