import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Brain, Briefcase, Building2, Inbox, Plus, Sparkles, Trash2, Wand2 } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, Loading, PageHeader, ScoreBadge } from "@/components/common";

function AddDialog({ open, onClose, onSaved }) {
  const [tab, setTab] = useState("paste");
  const [raw, setRaw] = useState("");
  const [parsing, setParsing] = useState(false);
  const [form, setForm] = useState({ company_name: "", job_title: "", job_description: "", required_skills: "" });
  const [busy, setBusy] = useState(false);

  const parse = async () => {
    if (!raw.trim()) return toast.error("Paste the job description first");
    setParsing(true);
    try {
      const res = await api.post("/opportunities/parse", { text: raw });
      setForm({
        company_name: res.data.company_name || "",
        job_title: res.data.job_title || "",
        job_description: raw,
        required_skills: (res.data.required_skills || []).join(", "),
      });
      toast.success("AI extracted the job details - review and save");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "AI parse failed");
    } finally { setParsing(false); }
  };

  const submit = async () => {
    if (!form.job_title.trim() && !form.job_description.trim()) return toast.error("Add a job title or description");
    setBusy(true);
    try {
      const payload = { ...form, required_skills: form.required_skills.split(",").map((s) => s.trim()).filter(Boolean), source: tab === "paste" ? "pasted_jd" : "manual" };
      const res = await api.post("/opportunities", payload);
      toast.success("Job opportunity added");
      onSaved(res.data); onClose();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
    finally { setBusy(false); }
  };

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="opportunity-dialog">
        <DialogHeader><DialogTitle>Add job opportunity</DialogTitle></DialogHeader>
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="paste">Paste description</TabsTrigger>
            <TabsTrigger value="manual">Manual entry</TabsTrigger>
          </TabsList>
          <TabsContent value="paste" className="space-y-3 mt-3">
            <Textarea rows={8} value={raw} onChange={(e) => setRaw(e.target.value)} placeholder="Paste the full job description here - AI will extract the company, title and required skills" data-testid="jd-paste-textarea" />
            <Button variant="secondary" onClick={parse} disabled={parsing} data-testid="ai-parse-button">
              <Wand2 className="mr-2 h-4 w-4" /> {parsing ? "Analyzing..." : "Analyze with AI"}
            </Button>
          </TabsContent>
        </Tabs>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1.5"><Label>Company name</Label><Input value={form.company_name} onChange={set("company_name")} data-testid="opp-company-input" /></div>
          <div className="space-y-1.5"><Label>Job title *</Label><Input value={form.job_title} onChange={set("job_title")} data-testid="opp-title-input" /></div>
          <div className="space-y-1.5 sm:col-span-2"><Label>Required skills (comma separated)</Label><Input value={form.required_skills} onChange={set("required_skills")} data-testid="opp-skills-input" /></div>
          <div className="space-y-1.5 sm:col-span-2"><Label>Job description</Label><Textarea rows={4} value={form.job_description} onChange={set("job_description")} data-testid="opp-description-input" /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={busy} data-testid="opp-save-button">{busy ? "Saving..." : "Add opportunity"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MatchDialog({ open, onClose, opportunity, onConfirmed }) {
  const [match, setMatch] = useState(null);
  const [versions, setVersions] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [running, setRunning] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const run = useCallback(async () => {
    if (!opportunity) return;
    setRunning(true);
    try {
      const res = await api.post(`/opportunities/${opportunity.id}/match`);
      setMatch(res.data);
      const rolesRes = await api.get("/roles");
      setProfiles(rolesRes.data);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail === "no_role_profiles") {
        toast.error("No role profiles yet - create one first", { action: { label: "Create", onClick: () => window.location.assign("/resumes") } });
      } else toast.error(detail || "AI matching failed");
    } finally { setRunning(false); }
  }, [opportunity]);

  useEffect(() => { if (open) { setMatch(null); run(); } }, [open, run]);

  useEffect(() => {
    if (match?.role_profile_id) {
      api.get(`/roles/${match.role_profile_id}/resumes`).then((r) => setVersions(r.data)).catch(() => setVersions([]));
    } else setVersions([]);
  }, [match?.role_profile_id]);

  const overrideRole = async (roleId) => {
    try {
      await api.post(`/opportunities/${opportunity.id}/match/confirm`, { role_profile_id: roleId });
      const fresh = await api.get(`/opportunities/${opportunity.id}`);
      setMatch(fresh.data.match);
      toast.success("Role profile overridden");
    } catch (e) { toast.error(e?.response?.data?.detail || "Override failed"); }
  };

  const overrideResume = async (versionId) => {
    try {
      await api.post(`/opportunities/${opportunity.id}/match/confirm`, { resume_version_id: versionId });
      const fresh = await api.get(`/opportunities/${opportunity.id}`);
      setMatch(fresh.data.match);
      toast.success("Resume version overridden");
    } catch (e) { toast.error(e?.response?.data?.detail || "Override failed"); }
  };

  const confirm = async () => {
    setConfirming(true);
    try {
      await api.post(`/opportunities/${opportunity.id}/match/confirm`, {});
      toast.success("Match confirmed - ready to generate the application email");
      onConfirmed(); onClose();
    } catch (e) { toast.error(e?.response?.data?.detail || "Confirm failed"); }
    finally { setConfirming(false); }
  };

  const selectedRole = profiles.find((p) => p.id === match?.role_profile_id);

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="match-dialog">
        <DialogHeader>
          <DialogTitle>AI job match — {opportunity?.job_title}</DialogTitle>
        </DialogHeader>
        {running ? (
          <div className="flex items-center gap-2 py-10 justify-center text-muted-foreground" data-testid="match-loading">
            <Brain className="h-5 w-5 animate-pulse" /> Analyzing job requirements against your role profiles...
          </div>
        ) : match ? (
          <div className="space-y-4" data-testid="match-result">
            <div className="flex flex-wrap items-center gap-3">
              <ScoreBadge score={match.score} />
              <Badge variant="outline" data-testid="match-confidence">Confidence: {match.confidence}</Badge>
              {match.confirmed && <Badge className="bg-emerald-500/15 text-emerald-600 border-emerald-500/30">Confirmed</Badge>}
            </div>
            <div className="rounded-lg border p-4" data-testid="match-reasoning">
              <p className="text-sm font-medium flex items-center gap-2"><Sparkles className="h-4 w-4 text-primary" /> Why this resume was selected</p>
              <p className="mt-2 text-sm text-muted-foreground">{match.reasoning}</p>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <p className="text-sm font-medium mb-2">Matched skills</p>
                <div className="flex flex-wrap gap-1.5" data-testid="matched-skills">
                  {match.matched_skills?.length ? match.matched_skills.map((s) => <Badge key={s} className="bg-emerald-500/15 text-emerald-600 border-emerald-500/30 text-xs font-normal">{s}</Badge>) : <p className="text-xs text-muted-foreground">None identified</p>}
                </div>
              </div>
              <div>
                <p className="text-sm font-medium mb-2">Missing skills</p>
                <div className="flex flex-wrap gap-1.5" data-testid="missing-skills">
                  {match.missing_skills?.length ? match.missing_skills.map((s) => <Badge key={s} variant="outline" className="text-xs font-normal text-rose-500 border-rose-500/30">{s}</Badge>) : <p className="text-xs text-muted-foreground">None</p>}
                </div>
              </div>
            </div>
            {match.ats && (
              <div className="rounded-lg border p-4" data-testid="ats-panel">
                <p className="text-sm font-medium">ATS resume analysis — {match.ats.score}/100</p>
                <p className="mt-1 text-xs text-muted-foreground">{match.ats.verdict}</p>
                {!!match.ats.suggestions?.length && (
                  <ul className="mt-2 list-disc pl-4 text-xs text-muted-foreground space-y-1">
                    {match.ats.suggestions.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                )}
              </div>
            )}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>Selected role profile</Label>
                <Select value={match.role_profile_id} onValueChange={overrideRole} data-testid="override-role-select">
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {profiles.map((p) => <SelectItem key={p.id} value={p.id}>{p.title}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Selected resume version</Label>
                <Select value={match.resume_version_id || ""} onValueChange={overrideResume} disabled={!selectedRole} data-testid="override-resume-select">
                  <SelectTrigger><SelectValue placeholder={match.resume_name ? `v${match.resume_version_no} - ${match.resume_name}` : "No resume"} /></SelectTrigger>
                  <SelectContent>
                    {versions.map((v) => (
                      <SelectItem key={v.id} value={v.id}>
                        {`v${v.version_no} - ${v.name}${v.active ? " (active)" : ""}`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            {!match.resume_version_id && (
              <p className="text-sm text-amber-600 dark:text-amber-400" data-testid="no-resume-warning">
                The selected role profile has no active resume. Upload one in <Link to="/resumes" className="underline">Resume & Role Profiles</Link>.
              </p>
            )}
            {match.alternatives?.length > 0 && (
              <div className="text-xs text-muted-foreground" data-testid="match-alternatives">
                Alternatives considered: {match.alternatives.map((a) => `${a.title} (${a.score}%)`).join(", ")}
              </div>
            )}
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={run} disabled={running} data-testid="rerun-match-button"><Brain className="mr-2 h-4 w-4" /> Re-run match</Button>
          <Button onClick={confirm} disabled={!match || confirming || !match.resume_version_id} data-testid="confirm-match-button">{confirming ? "Confirming..." : match?.confirmed ? "Save confirmation" : "Confirm match"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function Opportunities() {
  const [opps, setOpps] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [matchFor, setMatchFor] = useState(null);
  const [research, setResearch] = useState({});
  const [scanning, setScanning] = useState(false);

  const load = useCallback(async () => {
    try { setOpps((await api.get("/opportunities")).data); }
    catch { toast.error("Could not load opportunities"); setOpps([]); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const doResearch = async (opp) => {
    try {
      const res = await api.post(`/opportunities/${opp.id}/research`);
      setResearch((r) => ({ ...r, [opp.id]: res.data }));
      toast.success("Company research ready");
    } catch (e) { toast.error(e?.response?.data?.detail || "Research failed"); }
  };

  const scanInbox = async () => {
    setScanning(true);
    try {
      const res = await api.post("/opportunities/scan-inbox");
      toast.success(`Scanned ${res.data.scanned} emails - ${res.data.created.length} new opportunities found`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Inbox scan failed"); }
    finally { setScanning(false); }
  };

  const remove = async (opp) => {
    try { await api.delete(`/opportunities/${opp.id}`); toast.success("Opportunity deleted"); load(); }
    catch { toast.error("Could not delete"); }
  };

  if (opps === null) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Job Opportunities"
        subtitle="Paste job descriptions, import them, or let AI find them in your Gmail inbox"
        actions={
          <>
            <Button variant="outline" onClick={scanInbox} disabled={scanning} data-testid="scan-inbox-button">
              <Inbox className="mr-2 h-4 w-4" /> {scanning ? "Scanning inbox..." : "Scan Gmail inbox"}
            </Button>
            <Button onClick={() => setAddOpen(true)} data-testid="add-opportunity-button"><Plus className="mr-2 h-4 w-4" /> Add opportunity</Button>
          </>
        }
      />

      {opps.length === 0 ? (
        <EmptyState
          icon={Briefcase}
          title="No job opportunities yet"
          description="Paste a job description, import opportunities via CSV, or scan your Gmail inbox - AI will extract the details and match them against your role profiles."
          testId="opportunities-empty-state"
          actions={<Button onClick={() => setAddOpen(true)}><Plus className="mr-2 h-4 w-4" /> Add your first opportunity</Button>}
        />
      ) : (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3" data-testid="opportunities-grid">
          {opps.map((opp) => {
            const r = research[opp.id];
            return (
              <Card key={opp.id} className="flex flex-col" data-testid="opportunity-card">
                <CardContent className="flex flex-1 flex-col gap-3 p-5">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h3 className="font-display text-lg font-semibold" data-testid="opportunity-title">{opp.job_title || "Untitled role"}</h3>
                      <p className="flex items-center gap-1.5 text-sm text-muted-foreground"><Building2 className="h-3.5 w-3.5" /> {opp.company_name || "Unknown company"}</p>
                    </div>
                    <Badge variant="outline" className="text-xs font-normal">{opp.source?.replace("_", " ")}</Badge>
                  </div>
                  {opp.job_description && <p className="line-clamp-3 text-sm text-muted-foreground">{opp.job_description}</p>}
                  {!!opp.required_skills.length && (
                    <div className="flex flex-wrap gap-1.5">
                      {opp.required_skills.slice(0, 6).map((s) => <Badge key={s} variant="secondary" className="text-xs font-normal">{s}</Badge>)}
                    </div>
                  )}
                  {r && (
                    <div className="rounded-lg border bg-muted/40 p-3 text-xs text-muted-foreground" data-testid="company-research">
                      <p className="font-medium text-foreground">Company background</p>
                      <p className="mt-1">{r.background}</p>
                      <p className="mt-2 italic opacity-70">{r.caveat}</p>
                    </div>
                  )}
                  {opp.match && (
                    <div className="flex items-center gap-2">
                      <ScoreBadge score={opp.match.score} />
                      {opp.match.confirmed && <Badge variant="outline" className="text-emerald-500 border-emerald-500/30">Confirmed</Badge>}
                    </div>
                  )}
                  <div className="mt-auto flex flex-wrap gap-2">
                    <Button size="sm" onClick={() => setMatchFor(opp)} data-testid={`run-match-${opp.id}`}>
                      <Brain className="mr-1.5 h-3.5 w-3.5" /> {opp.match ? "View AI match" : "Run AI match"}
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => doResearch(opp)} data-testid={`research-${opp.id}`}>
                      <Sparkles className="mr-1.5 h-3.5 w-3.5" /> Research
                    </Button>
                    <Button size="sm" variant="ghost" className="text-red-500" onClick={() => remove(opp)} data-testid={`delete-opp-${opp.id}`}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <AddDialog open={addOpen} onClose={() => setAddOpen(false)} onSaved={load} />
      <MatchDialog open={!!matchFor} opportunity={matchFor} onClose={() => setMatchFor(null)} onConfirmed={load} />
    </div>
  );
}
