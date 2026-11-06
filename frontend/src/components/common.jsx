import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Loader2 } from "lucide-react";

export const STATUS_META = {
  draft: { label: "Draft", cls: "bg-slate-500/15 text-slate-700 dark:text-slate-300 border-slate-500/30" },
  awaiting_approval: { label: "Awaiting approval", cls: "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30" },
  queued_auto: { label: "Queued (auto)", cls: "bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30" },
  scheduled: { label: "Scheduled", cls: "bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 border-indigo-500/30" },
  approved: { label: "Approved", cls: "bg-teal-500/15 text-teal-700 dark:text-teal-300 border-teal-500/30" },
  sending: { label: "Sending...", cls: "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30 animate-pulse" },
  sent: { label: "Sent", cls: "bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30" },
  followed_up: { label: "Followed up", cls: "bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 border-indigo-500/30" },
  replied: { label: "HR replied", cls: "bg-violet-500/15 text-violet-700 dark:text-violet-300 border-violet-500/30" },
  interview: { label: "Interview", cls: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30" },
  rejected: { label: "Rejected", cls: "bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/30" },
  offer: { label: "Offer", cls: "bg-lime-500/15 text-lime-700 dark:text-lime-300 border-lime-500/30" },
  send_failed: { label: "Send failed", cls: "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30" },
  submitting: { label: "Submitting", cls: "bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30" },
  needs_attention: { label: "Needs your input", cls: "bg-orange-500/15 text-orange-700 dark:text-orange-300 border-orange-500/30" },
  bounced: { label: "Bounced", cls: "bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/30" },
  unsubscribed: { label: "Unsubscribed", cls: "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30" },
  cancelled: { label: "Cancelled", cls: "bg-slate-500/10 text-slate-500 border-slate-500/20" },
};

export function StatusBadge({ status, className = "" }) {
  const meta = STATUS_META[status] || { label: status, cls: "" };
  return (
    <Badge variant="outline" className={`${meta.cls} ${className}`} data-testid={`status-badge-${status}`}>
      {meta.label}
    </Badge>
  );
}

export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="text-muted-foreground mt-1 text-sm">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, description, actions, testId }) {
  return (
    <div
      className="flex flex-col items-center justify-center rounded-xl border border-dashed py-16 px-6 text-center"
      data-testid={testId || "empty-state"}
    >
      {Icon && (
        <div className="mb-4 rounded-full bg-primary/10 p-4">
          <Icon className="h-8 w-8 text-primary" />
        </div>
      )}
      <h3 className="text-lg font-semibold">{title}</h3>
      {description && <p className="mt-2 max-w-md text-sm text-muted-foreground">{description}</p>}
      {actions && <div className="mt-6 flex flex-wrap items-center justify-center gap-3">{actions}</div>}
    </div>
  );
}

export function StatCard({ label, value, icon: Icon, accent = "text-primary", testId, sub }) {
  return (
    <Card className="hover:-translate-y-0.5 transition-transform" data-testid={testId}>
      <CardContent className="p-5">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          {Icon && <Icon className={`h-5 w-5 ${accent}`} />}
        </div>
        <p className="mt-2 text-3xl font-bold tracking-tight" data-testid={testId ? `${testId}-value` : undefined}>
          {value}
        </p>
        {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  );
}

export function Loading({ label = "Loading..." }) {
  return (
    <div className="flex items-center justify-center py-24 gap-2 text-muted-foreground" data-testid="loading-state">
      <Loader2 className="h-5 w-5 animate-spin" />
      <span className="text-sm">{label}</span>
    </div>
  );
}

export function ScoreBadge({ score }) {
  const tone = score >= 70 ? "text-emerald-500 border-emerald-500/40" : score >= 40 ? "text-amber-500 border-amber-500/40" : "text-rose-500 border-rose-500/40";
  return (
    <Badge variant="outline" className={`font-semibold ${tone}`} data-testid="match-score-badge">
      {score}% match
    </Badge>
  );
}

export { Skeleton, Button };
