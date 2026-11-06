import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CalendarClock, Download, Inbox, MailCheck, Send, X } from "lucide-react";
import { api, downloadCsv } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, Loading, PageHeader, StatusBadge } from "@/components/common";

const STATUS_OPTIONS = ["replied", "interview", "rejected", "offer", "sent", "bounced", "unsubscribed"];

function InterviewDialog({ open, onClose, app, onSaved }) {
  const [when, setWhen] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open && app) {
      setWhen(app.interview_at ? new Date(app.interview_at).toISOString().slice(0, 16) : "");
      setNotes(app.interview_notes || "");
    }
  }, [open, app]);

  const save = async () => {
    if (!when) return toast.error("Pick a date and time");
    setBusy(true);
    try {
      await api.post(`/applications/${app.id}/schedule-interview`, {
        interview_at: new Date(when).toISOString(), notes,
      });
      toast.success("Interview scheduled - a reminder will arrive before it starts");
      onSaved();
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not schedule interview");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md" data-testid="interview-dialog">
        <DialogHeader><DialogTitle>Schedule interview — {app?.company}</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Date & time</Label>
            <Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} data-testid="interview-datetime-input" />
          </div>
          <div className="space-y-1.5">
            <Label>Notes (round, interviewer, mode...)</Label>
            <Textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. Technical round 2 with engineering manager - Google Meet" data-testid="interview-notes-input" />
          </div>
          <p className="text-xs text-muted-foreground">You'll get an in-app event and an email reminder before the interview.</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={busy} data-testid="interview-save-button">{busy ? "Saving..." : "Save interview"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function Tracker() {
  const [history, setHistory] = useState(null);
  const [followups, setFollowups] = useState(null);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState({});
  const [interviewFor, setInterviewFor] = useState(null);

  const load = useCallback(async () => {
    try {
      const [h, f] = await Promise.all([api.get("/tracking/history"), api.get("/followups?status=pending")]);
      setHistory(h.data); setFollowups(f.data);
    } catch { toast.error("Could not load tracker"); setHistory([]); setFollowups([]); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const scanReplies = async () => {
    toast.info("Scanning your Gmail inbox for HR replies...");
    try {
      const res = await api.post("/tracking/scan-replies");
      toast.success(`Scan complete: ${res.data.replies} new replies detected`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Reply scan failed"); }
  };

  const setStatus = async (app, status) => {
    try {
      await api.post(`/applications/${app.id}/status`, { status });
      toast.success(`${app.company} marked as ${status}`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not update status"); }
  };

  const saveAndSend = async (f) => {
    const edits = editing[f.id] || {};
    try {
      await api.put(`/followups/${f.id}`, { subject: edits.subject ?? f.subject, body_text: edits.body ?? f.body_text });
      await api.post(`/followups/${f.id}/send`);
      toast.success(`Follow-up sent to ${f.hr_email}`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not send follow-up"); }
  };

  const cancel = async (f) => {
    try { await api.post(`/followups/${f.id}/cancel`); toast.success("Follow-up cancelled"); load(); }
    catch { toast.error("Could not cancel"); }
  };

  if (history === null || followups === null) return <Loading />;

  const counts = history.reduce((acc, a) => { acc[a.status] = (acc[a.status] || 0) + 1; return acc; }, {});
  const pipeline = ["draft", "awaiting_approval", "queued_auto", "sent", "followed_up", "replied", "interview", "offer", "rejected", "send_failed"]
    .filter((s) => counts[s]);

  return (
    <div>
      <PageHeader
        title="Application Tracker"
        subtitle="Follow every application, HR replies and follow-ups"
        actions={
          <>
            <Button variant="outline" onClick={scanReplies} data-testid="scan-replies-button"><Inbox className="mr-2 h-4 w-4" /> Scan for replies</Button>
            <Button variant="outline" onClick={() => downloadCsv("/tracking/export")} data-testid="export-csv-button"><Download className="mr-2 h-4 w-4" /> Export CSV</Button>
          </>
        }
      />

      {history.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-8" data-testid="pipeline-chips">
          {pipeline.map((s) => (
            <Badge key={s} variant="outline" className="gap-1.5 px-3 py-1.5" data-testid={`pipeline-chip-${s}`}>
              <StatusBadge status={s} /> <span>{counts[s]}</span>
            </Badge>
          ))}
        </div>
      )}

      {followups.length > 0 && (
        <Card className="mb-8" data-testid="followups-section">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base"><MailCheck className="h-4 w-4 text-primary" /> Follow-ups awaiting your approval</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-xs text-muted-foreground">AI drafted these reminders for applications with no reply. Nothing is sent until you approve each one.</p>
            {followups.map((f) => {
              const edits = editing[f.id] || {};
              return (
                <div key={f.id} className="rounded-lg border p-4 space-y-3" data-testid="followup-card">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium">{f.company} — {f.job_title}</p>
                      <p className="text-xs text-muted-foreground">To: {f.hr_email} · Created {new Date(f.created_at).toLocaleDateString()}</p>
                    </div>
                    <div className="flex gap-2">
                      <Button size="sm" onClick={() => saveAndSend(f)} data-testid={`send-followup-${f.id}`}><Send className="mr-1.5 h-3.5 w-3.5" /> Approve & send</Button>
                      <Button size="sm" variant="outline" onClick={() => cancel(f)} data-testid={`cancel-followup-${f.id}`}><X className="mr-1.5 h-3.5 w-3.5" /> Cancel</Button>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs">Subject</Label>
                    <Input value={edits.subject ?? f.subject} onChange={(e) => setEditing({ ...editing, [f.id]: { ...edits, subject: e.target.value } })} data-testid={`followup-subject-${f.id}`} />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs">Body</Label>
                    <Textarea rows={5} value={edits.body ?? f.body_text} onChange={(e) => setEditing({ ...editing, [f.id]: { ...edits, body: e.target.value } })} data-testid={`followup-body-${f.id}`} />
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      <InterviewDialog open={!!interviewFor} app={interviewFor} onClose={() => setInterviewFor(null)} onSaved={load} />
      {history.length === 0 ? (
        <EmptyState
          icon={CalendarClock}
          title="No applications to track yet"
          description="Once you generate and send applications, every step appears here with the exact resume version used, HR replies and follow-up reminders."
          testId="tracker-empty-state"
        />
      ) : (
        <div className="rounded-xl border overflow-x-auto" data-testid="history-table">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Company</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>HR contact</TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Role profile / resume</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Latest response</TableHead>
                <TableHead>Next follow-up</TableHead>
                <TableHead>Interview</TableHead>
                <TableHead>Set status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {history
                .filter((a) => !search || `${a.company} ${a.job_title} ${a.hr_email}`.toLowerCase().includes(search.toLowerCase()))
                .map((a) => (
                <TableRow key={a.id} data-testid="history-row">
                  <TableCell className="font-medium">{a.company}</TableCell>
                  <TableCell>{a.job_title}</TableCell>
                  <TableCell className="text-muted-foreground">{a.hr_email}</TableCell>
                  <TableCell>{a.sent_at ? new Date(a.sent_at).toLocaleDateString() : "—"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {a.role_profile_title}
                    <br />{a.resume_name} (v{a.resume_version_no})
                  </TableCell>
                  <TableCell><StatusBadge status={a.status} /></TableCell>
                  <TableCell className="max-w-48 truncate text-xs text-muted-foreground">{a.latest_response || "—"}</TableCell>
                  <TableCell>{a.next_followup_at ? new Date(a.next_followup_at).toLocaleDateString() : "—"}</TableCell>
                  <TableCell>
                    {a.status === "interview" || a.interview_at ? (
                      <Button size="sm" variant="outline" onClick={() => setInterviewFor(a)} data-testid={`schedule-interview-${a.id}`}>
                        <CalendarClock className="mr-1.5 h-3.5 w-3.5" />
                        {a.interview_at ? new Date(a.interview_at).toLocaleString() : "Schedule"}
                      </Button>
                    ) : "—"}
                  </TableCell>
                  <TableCell>
                    <Select value={a.status} onValueChange={(s) => setStatus(a, s)}>
                      <SelectTrigger className="h-8 w-32 text-xs" data-testid={`status-select-${a.id}`}><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {STATUS_OPTIONS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
