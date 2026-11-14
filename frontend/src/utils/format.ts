export function formatDate(value: string | null | undefined, missingLabel = "Belirtilmemiş") {
  if (!value) return missingLabel;
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("tr-TR", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

export function formatTimestamp(value: string | null | undefined) {
  if (!value) return "Henüz güncellenmedi";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function formatBoolean(value: boolean | null) {
  if (value === null) return "Belirtilmemiş";
  return value ? "Evet" : "Hayır";
}
