import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, Download, Gauge, Pencil, Play, RefreshCw, Send, Trash2 } from "lucide-react";
import { api, downloadFile } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, Loading, PageHeader, ScoreBadge, StatCard, StatusBadge } from "@/components/common";
import { EmergencyStopButton } from "@/components/layout/AppShell";

function EditDialog({ open, onClose, app, onSaved }) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setSubject(app?.subject || ""); setBody(app?.body_text || ""); }, [open, app]);

  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/applications/${app.id}`, { subject, body_text: body });
      toast.success("Application updated");
      onSaved(); onClose();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl" data-testid="queue-edit-dialog">
        <DialogHeader><DialogTitle>Edit application — {app?.company}</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5"><Label>Subject</Label><Input value={subject} onChange={(e) => setSubject(e.target.value)} data-testid="queue-edit-subject" /></div>
          <div className="space-y-1.5"><Label>Body</Label><Textarea rows={12} value={body} onChange={(e) => setBody(e.target.value)} data-testid="queue-edit-body" /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={busy} data-testid="queue-edit-save">{busy ? "Saving..." : "Save"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function ApplicationQueue({ onChanged }) {
  const [apps, setApps] = useState(null);
  const [stats, setStats] = useState(null);
  const [tab, setTab] = useState("all");
  const [editFor, setEditFor] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    try {
      const [a, s] = await Promise.all([api.get("/applications"), api.get("/applications/queue-stats")]);
      setApps(a.data); setStats(s.data);
    } catch { toast.error("Could not load queue"); setApps([]); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const autopilot = stats?.autopilot || {};

  const setAutopilot = async (updates) => {
    try {
      const res = await api.put("/autopilot", updates);
      setStats({ ...stats, autopilot: res.data.autopilot });
      toast.success("Auto-pilot settings saved");
      onChanged && onChanged();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
  };

  const runNow = async () => {
    try {
      const res = await api.post("/autopilot/run-now");
      toast.success(`Auto-pilot cycle finished: ${res.data.sent} sent, ${res.data.failed} failed, ${res.data.skipped} skipped`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Cycle failed"); }
  };

  const act = async (app, action) => {
    setBusyId(app.id);
    try {
      await api.post(`/applications/${app.id}/${action}`);
      const messages = { approve: "Application approved", send: "Sent via Gmail", retry: "Queued for retry" };
      toast.success(messages[action] || "Done");
      load(); onChanged && onChanged();
    } catch (e) { toast.error(e?.response?.data?.detail || "Action failed"); }
    finally { setBusyId(null); }
  };

  const remove = async (app) => {
    try {
      const res = await api.delete(`/applications/${app.id}`);
      toast.success(res.data?.cancelled ? "Sent application cancelled" : "Application deleted");
      load(); onChanged && onChanged();
    } catch { toast.error("Could not delete"); }
  };

  if (apps === null) return <Loading />;

  const filtered = tab === "all" ? apps : apps.filter((a) => a.status === tab);
  const sentToday = stats?.sent_today || 0;
  const dailyLimit = autopilot.max_per_day || 10;

  return (
    <div>
      <PageHeader title="Application Queue" subtitle="Every generated application - review, approve, send or let auto-pilot run" />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3 mb-8">
        <Card className="lg:col-span-2" data-testid="autopilot-panel">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base"><Gauge className="h-4 w-4 text-primary" /> Auto-Pilot controls</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>Sending mode</Label>
                <Select value={autopilot.mode || "approval"} onValueChange={(mode) => setAutopilot({ mode })} data-testid="autopilot-mode-select">
                  <SelectTrigger data-testid="autopilot-mode-trigger"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="manual">Manual - drafts only</SelectItem>
                    <SelectItem value="approval">Approval - wait for my OK</SelectItem>
                    <SelectItem value="auto">Auto-send eligible applications</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Daily sending limit</Label>
                <Input type="number" min="1" max="50" defaultValue={autopilot.max_per_day || 10} onBlur={(e) => setAutopilot({ max_per_day: Number(e.target.value) })} data-testid="autopilot-daily-limit" />
              </div>
              <div className="space-y-1.5">
                <Label>Minimum delay between sends (minutes)</Label>
                <Input type="number" min="1" max="1440" defaultValue={autopilot.min_delay_minutes || 30} onBlur={(e) => setAutopilot({ min_delay_minutes: Number(e.target.value) })} data-testid="autopilot-delay" />
              </div>
              <div className="space-y-1.5">
                <Label>Retry limit per application</Label>
                <Input type="number" min="0" max="5" defaultValue={autopilot.max_retries ?? 2} onBlur={(e) => setAutopilot({ max_retries: Number(e.target.value) })} data-testid="autopilot-retries" />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-4 pt-2">
              <div className="flex items-center gap-2">
                <Switch checked={!!autopilot.enabled} onCheckedChange={(enabled) => setAutopilot({ enabled })} data-testid="autopilot-toggle" />
                <span className="text-sm">Auto-pilot {autopilot.enabled ? "on" : "off"}</span>
              </div>
              <Button variant="outline" size="sm" onClick={runNow} data-testid="autopilot-run-now"><Play className="mr-1.5 h-3.5 w-3.5" /> Run cycle now</Button>
              <EmergencyStopButton testId="emergency-stop-button-queue" onChanged={() => { load(); onChanged && onChanged(); }} />
            </div>
            {autopilot.paused && (
              <p className="flex items-center gap-2 text-sm text-red-500" data-testid="autopilot-paused-warning">
                <AlertTriangle className="h-4 w-4" /> Emergency stop is active - no automatic sending until you toggle auto-pilot off and on again.
              </p>
            )}
          </CardContent>
        </Card>

        <div className="grid grid-cols-2 gap-4">
          <StatCard label="Sent today" value={`${sentToday}/${dailyLimit}`} icon={Send} testId="queue-sent-today" />
          <StatCard label="Awaiting approval" value={stats?.counts?.awaiting_approval || 0} icon={CheckCircle2} testId="queue-awaiting" />
          <StatCard label="Queued (auto)" value={stats?.counts?.queued_auto || 0} icon={Gauge} testId="queue-queued" />
          <StatCard label="Failed" value={stats?.counts?.send_failed || 0} icon={AlertTriangle} testId="queue-failed" />
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab} className="mb-6">
        <TabsList className="flex-wrap h-auto" data-testid="queue-tabs">
          <TabsTrigger value="all">All ({apps.length})</TabsTrigger>
          <TabsTrigger value="draft">Drafts</TabsTrigger>
          <TabsTrigger value="awaiting_approval">Awaiting approval</TabsTrigger>
          <TabsTrigger value="queued_auto">Queued</TabsTrigger>
          <TabsTrigger value="sent">Sent</TabsTrigger>
          <TabsTrigger value="send_failed">Failed</TabsTrigger>
        </TabsList>
      </Tabs>

      {filtered.length === 0 ? (
        <EmptyState
          icon={Send}
          title={tab === "all" ? "No applications yet" : "Nothing here"}
          description={tab === "all" ? "Generate your first application email from a job opportunity in the AI Email Generator." : `No applications with status "${tab}".`}
          testId="queue-empty-state"
        />
      ) : (
        <div className="space-y-4" data-testid="queue-list">
          {filtered.map((app) => (
            <Card key={app.id} data-testid="queue-application-card">
              <CardContent className="p-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-display font-semibold">{app.company}</h3>
                      <StatusBadge status={app.status} />
                      <ScoreBadge score={app.match_score} />
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {app.job_title} · {app.channel === "board" ? `Job board: ${app.board}` : app.hr_email} · Resume: {app.resume_name} (v{app.resume_version_no})
                    </p>
                    <p className="mt-3 text-sm font-medium">{app.subject}</p>
                    <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-sm text-muted-foreground">{app.body_text}</p>
                    {app.error && <p className="mt-2 text-xs text-red-500" data-testid="application-error">{app.error}</p>}
                    {app.sent_at && <p className="mt-2 text-xs text-muted-foreground">Sent {new Date(app.sent_at).toLocaleString()} from {app.gmail_email}</p>}
                  </div>
                  <div className="flex flex-wrap gap-2 lg:flex-col lg:items-end">
                    {(app.status === "awaiting_approval" || app.status === "draft") && (
                      <Button size="sm" variant="outline" onClick={() => act(app, "approve")} disabled={busyId === app.id} data-testid={`approve-${app.id}`}><CheckCircle2 className="mr-1.5 h-3.5 w-3.5" /> Approve</Button>
                    )}
                    {app.channel === "board" && app.job_url && (
                      <Button size="sm" variant="outline" asChild data-testid={`open-job-${app.id}`}><a href={app.job_url} target="_blank" rel="noreferrer">Open job</a></Button>
                    )}
                    {app.channel !== "board" && ["draft", "awaiting_approval", "approved"].includes(app.status) && (
                      <Button size="sm" onClick={() => act(app, "send")} disabled={busyId === app.id} data-testid={`send-${app.id}`}><Send className="mr-1.5 h-3.5 w-3.5" /> Send now</Button>
                    )}
                    {["send_failed", "needs_attention"].includes(app.status) && (
                      <Button size="sm" variant="outline" onClick={() => act(app, "retry")} disabled={busyId === app.id} data-testid={`retry-${app.id}`}><RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Retry</Button>
                    )}
                    {!["sent", "cancelled"].includes(app.status) && (
                      <Button size="sm" variant="outline" onClick={() => setEditFor(app)} data-testid={`edit-${app.id}`}><Pencil className="mr-1.5 h-3.5 w-3.5" /> Edit</Button>
                    )}
                    <Button size="sm" variant="outline" onClick={() => downloadFile(`/applications/${app.id}/attachment`, app.attachment_filename || "resume.pdf")} data-testid={`attachment-${app.id}`}><Download className="mr-1.5 h-3.5 w-3.5" /> Attachment</Button>
                    <Button size="sm" variant="ghost" className="text-red-500" onClick={() => remove(app)} data-testid={`delete-${app.id}`}><Trash2 className="h-3.5 w-3.5" /></Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <EditDialog open={!!editFor} app={editFor} onClose={() => setEditFor(null)} onSaved={load} />
    </div>
  );
}
