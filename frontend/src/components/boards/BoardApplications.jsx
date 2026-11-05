import { useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, ExternalLink, Globe, Mail, RefreshCw, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { EmptyState, ScoreBadge, StatusBadge } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

function Actions({ app, busy, act }) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="outline" asChild data-testid={`board-open-${app.id}`}>
        <a href={app.job_url} target="_blank" rel="noreferrer"><ExternalLink className="mr-1.5 h-3.5 w-3.5" /> Open job</a>
      </Button>
      {["awaiting_approval", "draft"].includes(app.status) && (
        <Button size="sm" onClick={() => act(app, "approve")} disabled={busy} data-testid={`board-approve-${app.id}`}>
          <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" /> Approve
        </Button>
      )}
      {["needs_attention", "send_failed"].includes(app.status) && (
        <Button size="sm" variant="outline" onClick={() => act(app, "retry")} disabled={busy} data-testid={`board-retry-${app.id}`}>
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Try again
        </Button>
      )}
      {app.has_hr_email && !["sent", "cancelled"].includes(app.status) && (
        <Button size="sm" variant="outline" onClick={() => act(app, "email")} disabled={busy} data-testid={`board-email-${app.id}`}>
          <Mail className="mr-1.5 h-3.5 w-3.5" /> Apply by email instead
        </Button>
      )}
      {!["sent", "cancelled"].includes(app.status) && (
        <Button size="sm" variant="ghost" className="text-red-500" onClick={() => act(app, "cancel")} disabled={busy} data-testid={`board-cancel-${app.id}`}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  );
}

export function BoardApplications({ apps, boards, onChanged }) {
  const [busyId, setBusyId] = useState(null);
  const act = async (app, action) => {
    setBusyId(app.id);
    try {
      if (action === "approve") await api.post(`/applications/${app.id}/approve`);
      if (action === "retry") await api.post(`/applications/${app.id}/retry`);
      if (action === "cancel") await api.post(`/applications/${app.id}/status`, { status: "cancelled" });
      if (action === "email") await api.post(`/boards/applications/${app.id}/switch-to-email`);
      toast.success({ approve: "Approved - the helper will submit it", retry: "Queued again", cancel: "Cancelled",
        email: "Email draft created in the Application Queue" }[action]);
      onChanged();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Action failed");
    } finally {
      setBusyId(null);
    }
  };
  if (!apps.length) {
    return (
      <EmptyState icon={Globe} testId="board-apps-empty" title="No board applications yet"
        description="Save jobs with the browser helper or run an automatic search. Each job is matched to your best role profile and resume, then prepared here." />
    );
  }
  return (
    <div className="space-y-3" data-testid="board-apps-list">
      {apps.map((app) => (
        <Card key={app.id} data-testid="board-app-card">
          <CardContent className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-semibold">{app.job_title}</h3>
                <Badge variant="outline" data-testid="board-app-board">{boards[app.board]?.label || app.board}</Badge>
                <StatusBadge status={app.status} />
                <ScoreBadge score={app.match_score} />
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {app.company || "Company not listed"} · Resume: {app.resume_name} (v{app.resume_version_no}) · {app.role_profile_title}
              </p>
              {app.error && <p className="mt-1 text-xs text-orange-500" data-testid="board-app-error">{app.error}</p>}
              {app.sent_at && <p className="mt-1 text-xs text-muted-foreground">Submitted {new Date(app.sent_at).toLocaleString()}</p>}
            </div>
            <Actions app={app} busy={busyId === app.id} act={act} />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
