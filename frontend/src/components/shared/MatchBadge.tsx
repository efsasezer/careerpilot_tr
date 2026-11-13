import type { MatchCategory } from "../../types/api";

export function MatchBadge({ category }: { category: MatchCategory }) {
  const style = category === "UYGUN" ? "badge-match" : category === "UYGUN DEĞİL" ? "badge-fail" : "badge-potential";
  return <span className={`match-badge ${style}`}>{category}</span>;
}
