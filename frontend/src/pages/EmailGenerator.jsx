import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Brain, CheckCircle2, FileEdit, Mail, Send, Wand2 } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, Loading, PageHeader, ScoreBadge, StatusBadge } from "@/components/common";

export default function EmailGenerator() {
  const [opps, setOpps] = useState(null);
  const [oppId, setOppId] = useState("");
  const [oppDetail, setOppDetail] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);

  const loadOpps = useCallback(async () => {
    try { setOpps((await api.get("/opportunities")).data); }
    catch { toast.error("Could not load opportunities"); setOpps([]); }
  }, []);
  useEffect(() => { loadOpps(); }, [loadOpps]);

  const selectOpp = async (id) => {
    setOppId(id); setDraft(null);
    if (!id) return setOppDetail(null);
    try { setOppDetail((await api.get(`/opportunities/${id}`)).data); }
    catch { toast.error("Could not load opportunity"); }
  };

  const opp = (opps || []).find((o) => o.id === oppId);

  const generate = async () => {
    if (!oppId) return;
    setGenerating(true);
    try {
      const res = await api.post("/applications/generate", { opportunity_id: oppId });
      setDraft(res.data);
      toast.success(`Personalized email drafted (${res.data.status === "queued_auto" ? "queued for auto-pilot" : res.data.status === "draft" ? "manual mode" : "awaiting your approval"})`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Email generation failed");
    } finally { setGenerating(false); }
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      await api.put(`/applications/${draft.id}`, { subject: draft.subject, body_text: draft.body_text });
      toast.success("Draft saved");
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
    finally { setSaving(false); }
  };

  const send = async () => {
    if (!draft) return;
    setSending(true);
    try {
      await api.put(`/applications/${draft.id}`, { subject: draft.subject, body_text: draft.body_text });
      await api.post(`/applications/${draft.id}/send`);
      toast.success("Application sent via Gmail with resume attached");
      setDraft({ ...draft, status: "sent" });
      loadOpps();
    } catch (e) { toast.error(e?.response?.data?.detail || "Send failed"); }
    finally { setSending(false); }
  };

  const approve = async () => {
    try {
      await api.post(`/applications/${draft.id}/approve`);
      toast.success("Application approved - send it now or from the queue");
      setDraft({ ...draft, status: "approved" });
    } catch (e) { toast.error(e?.response?.data?.detail || "Approve failed"); }
  };

  if (opps === null) return <Loading />;

  if (opps.length === 0) {
    return (
      <div>
        <PageHeader title="AI Email Generator" subtitle="Match an opportunity to a role profile and generate a personalized email" />
        <EmptyState
          icon={Mail}
          title="No opportunities to generate emails for"
          description="Add a job opportunity first - AI will match it against your role profiles and select the right resume."
          testId="generator-empty-state"
          actions={<Button asChild><Link to="/opportunities">Add a job opportunity</Link></Button>}
        />
      </div>
    );
  }

  const match = oppDetail?.match;
  const unmatched = oppId && (!match || !match.confirmed);

  return (
    <div>
      <PageHeader title="AI Email Generator" subtitle="AI matching, resume selection and personalized email drafting" />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-1">
          <Card>
            <CardContent className="space-y-4 p-5">
              <div className="space-y-1.5">
                <Label>Job opportunity</Label>
                <Select value={oppId} onValueChange={selectOpp} data-testid="generator-opportunity-select">
                  <SelectTrigger data-testid="generator-opportunity-trigger"><SelectValue placeholder="Choose an opportunity" /></SelectTrigger>
                  <SelectContent>
                    {opps.map((o) => (
                      <SelectItem key={o.id} value={o.id}>{o.job_title} — {o.company_name || "Unknown"}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {match && (
                <div className="rounded-lg border p-3 space-y-2" data-testid="generator-match-summary">
                  <div className="flex items-center gap-2 flex-wrap">
                    <ScoreBadge score={match.score} />
                    <Badge variant="outline" className="text-xs">Confidence: {match.confidence}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">{match.reasoning}</p>
                  <div className="text-xs">
                    <p className="font-medium">Role profile: <span className="font-normal">{match.role_profile_title}</span></p>
                    <p className="font-medium mt-1">Resume: <span className="font-normal">{match.resume_name ? `v${match.resume_version_no} — ${match.resume_name}` : "none uploaded"}</span></p>
                  </div>
                  {!match.confirmed && (
                    <p className="text-xs text-amber-600 dark:text-amber-400">
                      {match.score < 50
                        ? "Low match confidence - review the match in Job Opportunities and confirm or override the selection before sending."
                        : "Confirm the match in Job Opportunities to enable auto-pilot sending."}
                    </p>
                  )}
                </div>
              )}

              <Button className="w-full" onClick={generate} disabled={!oppId || generating} data-testid="generate-email-button">
                <Wand2 className="mr-2 h-4 w-4" /> {generating ? "Writing your email..." : "Generate personalized email"}
              </Button>
              {unmatched && (
                <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                  <Brain className="h-3.5 w-3.5" /> Tip: confirm the AI match on the opportunity card for full auto-pilot eligibility.
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-2">
          {generating ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center gap-3 py-24 text-muted-foreground" data-testid="generating-state">
                <Brain className="h-8 w-8 animate-pulse text-primary" />
                <p className="text-sm">AI is analyzing the job description, your role profile and resume to write a unique email for {opp?.company_name || "this company"}...</p>
              </CardContent>
            </Card>
          ) : draft ? (
            <Card data-testid="email-draft-card">
              <CardContent className="space-y-4 p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <FileEdit className="h-4 w-4 text-primary" />
                    <span className="text-sm font-medium">To: {draft.hr_email}</span>
                  </div>
                  <StatusBadge status={draft.status} data-testid="draft-status" />
                </div>
                <div className="space-y-1.5">
                  <Label>Subject</Label>
                  <Input value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} data-testid="draft-subject-input" />
                </div>
                <div className="space-y-1.5">
                  <Label>Email body (editable)</Label>
                  <Textarea rows={14} value={draft.body_text} onChange={(e) => setDraft({ ...draft, body_text: e.target.value })} className="font-[inherit] text-sm leading-relaxed" data-testid="draft-body-input" />
                </div>
                <div className="rounded-lg border bg-muted/40 p-3 text-xs text-muted-foreground" data-testid="draft-meta">
                  Resume attached: <strong>{draft.resume_name} (v{draft.resume_version_no})</strong> · Role profile: <strong>{draft.role_profile_title}</strong> · Match score: <strong>{draft.match_score}%</strong>
                </div>
                <div className="flex flex-wrap gap-3">
                  <Button variant="outline" onClick={save} disabled={saving} data-testid="save-draft-button">Save edits</Button>
                  {(draft.status === "awaiting_approval" || draft.status === "draft") && (
                    <Button variant="secondary" onClick={approve} data-testid="approve-draft-button"><CheckCircle2 className="mr-2 h-4 w-4" /> Approve</Button>
                  )}
                  {draft.status !== "sent" && (
                    <Button onClick={send} disabled={sending} data-testid="send-now-button"><Send className="mr-2 h-4 w-4" /> {sending ? "Sending..." : "Send now via Gmail"}</Button>
                  )}
                  {draft.status === "sent" && <Badge className="bg-emerald-500/15 text-emerald-600 border-emerald-500/30">Sent with resume attached</Badge>}
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="flex flex-col items-center justify-center gap-3 py-24 text-muted-foreground" data-testid="generator-placeholder">
                <Mail className="h-8 w-8 opacity-50" />
                <p className="text-sm">Select an opportunity and generate a personalized, human-sounding application email.</p>
                <p className="text-xs">The AI only uses facts from your resume and the job description - never invented achievements.</p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
