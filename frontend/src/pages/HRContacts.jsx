import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { AlertCircle, CheckCircle2, Download, Loader2, Pencil, Plus, Sparkles, Trash2, Upload, Users } from "lucide-react";
import { api, downloadFile } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, Loading, PageHeader } from "@/components/common";

const BLANK = { company_name: "", hr_name: "", hr_email: "", company_website: "", job_role: "", job_description: "", application_source: "", notes: "" };

function ContactDialog({ open, onClose, contact, onSaved }) {
  const [form, setForm] = useState(BLANK);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setForm(contact ? { ...BLANK, ...contact } : BLANK); }, [open, contact]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = async () => {
    setBusy(true);
    try {
      const res = contact ? await api.put(`/contacts/${contact.id}`, form) : await api.post("/contacts", form);
      toast.success(contact ? "Contact updated" : "Contact added");
      onSaved(res.data); onClose();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (e?.response?.status === 409) toast.warning(detail || "Duplicate contact");
      else toast.error(detail || "Could not save contact");
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg" data-testid="contact-dialog">
        <DialogHeader><DialogTitle>{contact ? "Edit HR contact" : "Add HR contact"}</DialogTitle></DialogHeader>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1.5"><Label>Company name</Label><Input value={form.company_name} onChange={set("company_name")} data-testid="contact-company-input" /></div>
          <div className="space-y-1.5"><Label>HR name</Label><Input value={form.hr_name} onChange={set("hr_name")} data-testid="contact-hr-name-input" /></div>
          <div className="space-y-1.5 sm:col-span-2"><Label>HR email *</Label><Input type="email" value={form.hr_email} onChange={set("hr_email")} placeholder="hr@company.com" data-testid="contact-email-input" /></div>
          <div className="space-y-1.5"><Label>Company website</Label><Input value={form.company_website} onChange={set("company_website")} data-testid="contact-website-input" /></div>
          <div className="space-y-1.5"><Label>Job role</Label><Input value={form.job_role} onChange={set("job_role")} data-testid="contact-role-input" /></div>
          <div className="space-y-1.5 sm:col-span-2"><Label>Job description</Label><Textarea rows={2} value={form.job_description} onChange={set("job_description")} data-testid="contact-description-input" /></div>
          <div className="space-y-1.5"><Label>Application source</Label><Input value={form.application_source} onChange={set("application_source")} placeholder="LinkedIn, referral..." data-testid="contact-source-input" /></div>
          <div className="space-y-1.5"><Label>Notes</Label><Input value={form.notes} onChange={set("notes")} data-testid="contact-notes-input" /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={busy} data-testid="contact-save-button">{busy ? "Saving..." : "Save contact"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ImportDialog({ open, onClose, onImported }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => { setFile(null); setResult(null); }, [open]);

  const submit = async () => {
    if (!file) return toast.error("Choose a CSV or Excel file");
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.post("/contacts/import", fd);
      setResult(res.data);
      onImported();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Import failed");
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg" data-testid="import-dialog">
        <DialogHeader><DialogTitle>Import HR contacts</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Upload a CSV or Excel file with columns: company name, HR name, HR email, company website, job role,
            job description, application source, notes. Only the email column is required.
          </p>
          <Input type="file" accept=".csv,.xlsx,.xls,text/csv" onChange={(e) => setFile(e.target.files?.[0] || null)} data-testid="import-file-input" />
          {result && (
            <div className="rounded-lg border p-3 text-sm" data-testid="import-result">
              <p className="font-medium text-emerald-600 dark:text-emerald-400">{result.imported} contacts imported</p>
              {!!result.duplicates.length && <p className="mt-1 text-amber-600 dark:text-amber-400">{result.duplicates.length} duplicates skipped:</p>}
              <ul className="mt-1 max-h-32 overflow-y-auto text-xs text-muted-foreground">
                {result.duplicates.slice(0, 10).map((d, i) => <li key={i}>Row {d.row}: {d.reason}</li>)}
                {!!result.errors.length && result.errors.slice(0, 5).map((d, i) => <li key={`e${i}`}>Row {d.row}: {d.reason}</li>)}
              </ul>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{result ? "Done" : "Cancel"}</Button>
          <Button onClick={submit} disabled={busy || !file} data-testid="import-confirm-button">{busy ? "Importing..." : "Import"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ContactStatusBadge({ status }) {
  switch (status) {
    case "sent":
      return <Badge className="bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 border-emerald-200">Sent</Badge>;
    case "approved":
      return <Badge className="bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300 border-purple-200">Approved</Badge>;
    case "replied":
      return <Badge className="bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-300 border-teal-200">Replied</Badge>;
    case "bounced":
      return <Badge variant="destructive">Bounced</Badge>;
    case "draft":
      return <Badge variant="secondary" className="bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300 border-sky-200">Draft</Badge>;
    default:
      return <Badge variant="outline" className="text-muted-foreground">No application</Badge>;
  }
}

function BulkGenerateDialog({ open, onClose, selectedIds, onFinished }) {
  const [queueForAuto, setQueueForAuto] = useState(false);
  const [activeJob, setActiveJob] = useState(null);
  const [starting, setStarting] = useState(false);
  const pollTimer = useRef(null);

  const fetchActive = useCallback(async () => {
    try {
      const res = await api.get("/contacts/bulk-jobs/active");
      if (res.data?.job) {
        setActiveJob(res.data.job);
        return res.data.job;
      }
    } catch {}
    return null;
  }, []);

  useEffect(() => {
    if (!open) {
      if (pollTimer.current) clearInterval(pollTimer.current);
      return;
    }
    fetchActive();
    pollTimer.current = setInterval(async () => {
      const job = await fetchActive();
      if (!job || job.status === "completed" || job.status === "failed") {
        clearInterval(pollTimer.current);
        if (job?.status === "completed") {
          toast.success(`Bulk generation complete: ${job.done} generated, ${job.skipped} skipped, ${job.failed} failed`);
          onFinished && onFinished();
        }
      }
    }, 1500);

    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
  }, [open, fetchActive, onFinished]);

  const start = async () => {
    setStarting(true);
    try {
      const res = await api.post("/contacts/bulk-generate", {
        contact_ids: Array.from(selectedIds),
        queue_for_auto: queueForAuto,
      });
      setActiveJob(res.data);
      toast.info("Bulk generation started in background");
      if (pollTimer.current) clearInterval(pollTimer.current);
      pollTimer.current = setInterval(async () => {
        try {
          const check = await api.get(`/contacts/bulk-jobs/${res.data.id}`);
          setActiveJob(check.data);
          if (check.data.status === "completed" || check.data.status === "failed") {
            clearInterval(pollTimer.current);
            if (check.data.status === "completed") {
              toast.success(`Bulk generation complete: ${check.data.done} generated, ${check.data.skipped} skipped, ${check.data.failed} failed`);
              onFinished && onFinished();
            }
          }
        } catch {}
      }, 1500);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not start bulk generation");
    } finally {
      setStarting(false);
    }
  };

  const total = activeJob?.total || selectedIds.length;
  const processed = activeJob ? (activeJob.done || 0) + (activeJob.skipped || 0) + (activeJob.failed || 0) : 0;
  const progressPct = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  const isRunning = activeJob && (activeJob.status === "pending" || activeJob.status === "running");
  const isDone = activeJob && (activeJob.status === "completed" || activeJob.status === "failed");

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-xl" data-testid="bulk-generate-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            {isRunning ? "Generating applications..." : isDone ? "Generation results" : "Generate applications for contacts"}
          </DialogTitle>
        </DialogHeader>

        {!activeJob ? (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Generate tailored application emails and role matchings for{" "}
              <strong>{selectedIds.length}</strong> selected contact{selectedIds.length === 1 ? "" : "s"}.
            </p>
            <div className="rounded-lg border bg-muted/30 p-3 space-y-2 text-xs text-muted-foreground">
              <p>• Automatically reuses or creates job opportunities from the contact role & description.</p>
              <p>• Employs match caching to prevent repeated AI calls for identical job roles.</p>
              <p>• Validates emails, skips role accounts (e.g. noreply@), and enforces strict anti-placeholder guardrails.</p>
              <p>• Deterministically appends your profile signature to every generated email.</p>
            </div>
            <div className="flex items-center justify-between rounded-lg border p-3">
              <div>
                <p className="text-sm font-medium">Queue for auto-send</p>
                <p className="text-xs text-muted-foreground">
                  Only queues if autopilot mode is 'auto', match score meets your threshold, and daily cap allows. By default, drafts land in 'Awaiting Approval' for your review.
                </p>
              </div>
              <Switch checked={queueForAuto} onCheckedChange={setQueueForAuto} data-testid="bulk-queue-auto-switch" />
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="font-medium text-foreground">
                  {isRunning ? "Processing contacts..." : activeJob.status === "completed" ? "Finished" : "Job failed"}
                </span>
                <span className="text-muted-foreground">{processed} / {total} ({progressPct}%)</span>
              </div>
              <Progress value={progressPct} className="h-2.5" />
            </div>

            <div className="grid grid-cols-4 gap-2 text-center">
              <div className="rounded-lg border bg-card p-2">
                <p className="text-xs text-muted-foreground">Done</p>
                <p className="text-lg font-semibold text-emerald-600 dark:text-emerald-400">{activeJob.done || 0}</p>
              </div>
              <div className="rounded-lg border bg-card p-2">
                <p className="text-xs text-muted-foreground">Skipped</p>
                <p className="text-lg font-semibold text-amber-600 dark:text-amber-400">{activeJob.skipped || 0}</p>
              </div>
              <div className="rounded-lg border bg-card p-2">
                <p className="text-xs text-muted-foreground">Failed</p>
                <p className="text-lg font-semibold text-rose-600 dark:text-rose-400">{activeJob.failed || 0}</p>
              </div>
              <div className="rounded-lg border bg-card p-2">
                <p className="text-xs text-muted-foreground">Total</p>
                <p className="text-lg font-semibold">{total}</p>
              </div>
            </div>

            {!!activeJob.errors?.length && (
              <div className="space-y-1.5">
                <p className="text-xs font-medium">Skipped & error details ({activeJob.errors.length}):</p>
                <div className="rounded-lg border bg-muted/20 p-2.5 max-h-36 overflow-y-auto space-y-1 text-xs">
                  {activeJob.errors.map((err, i) => (
                    <div key={i} className="flex items-start gap-1.5 text-muted-foreground">
                      <span className="font-mono text-amber-600 dark:text-amber-400 shrink-0">{err.email || "Contact"}:</span>
                      <span>{err.reason}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          {!activeJob ? (
            <>
              <Button variant="outline" onClick={onClose}>Cancel</Button>
              <Button onClick={start} disabled={starting || selectedIds.length === 0} data-testid="start-bulk-generate-button">
                {starting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
                {starting ? "Starting..." : "Generate applications"}
              </Button>
            </>
          ) : isRunning ? (
            <Button variant="outline" onClick={onClose}>Run in background</Button>
          ) : (
            <Button onClick={() => { setActiveJob(null); onClose(); onFinished && onFinished(); }}>Done</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function HRContacts() {
  const [contacts, setContacts] = useState(null);
  const [search, setSearch] = useState("");
  const [dialog, setDialog] = useState({ open: false, contact: null });
  const [importOpen, setImportOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkOpen, setBulkOpen] = useState(false);
  const [activeJob, setActiveJob] = useState(null);

  const load = useCallback(async (q = "") => {
    try {
      const [res, jobRes] = await Promise.all([
        api.get(`/contacts${q ? `?search=${encodeURIComponent(q)}` : ""}`),
        api.get("/contacts/bulk-jobs/active").catch(() => ({ data: { job: null } })),
      ]);
      setContacts(res.data);
      if (jobRes.data?.job) setActiveJob(jobRes.data.job);
      else setActiveJob(null);
    } catch {
      toast.error("Could not load contacts");
      setContacts([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const remove = async (c) => {
    try {
      await api.delete(`/contacts/${c.id}`);
      toast.success("Contact deleted");
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(c.id);
        return next;
      });
      load(search);
    } catch {
      toast.error("Could not delete contact");
    }
  };

  const exportTemplate = () => {
    const csv = "company_name,hr_name,hr_email,company_website,job_role,job_description,application_source,notes\n";
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "hr-contacts-template.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  if (contacts === null) return <Loading />;

  const visibleIds = contacts.map((c) => c.id);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));

  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAllVisible = () => {
    if (allVisibleSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(visibleIds));
    }
  };

  const selectWithoutApp = () => {
    const withoutApp = contacts.filter((c) => !c.application_status || c.application_status === "no_application").map((c) => c.id);
    if (withoutApp.length === 0) {
      toast.info("All contacts already have an application");
    } else {
      setSelectedIds(new Set(withoutApp));
      toast.success(`Selected ${withoutApp.length} contact${withoutApp.length === 1 ? "" : "s"} without applications`);
    }
  };

  return (
    <div>
      <PageHeader
        title="HR Contacts"
        subtitle="Your recruiter and HR network - import or add manually"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {activeJob && (
              <Button variant="secondary" size="sm" onClick={() => setBulkOpen(true)} data-testid="view-active-bulk-job">
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin text-primary" /> Active Generation ({activeJob.done}/{activeJob.total})
              </Button>
            )}
            <Button variant="outline" onClick={() => setImportOpen(true)} data-testid="import-contacts-button"><Upload className="mr-2 h-4 w-4" /> Import CSV/Excel</Button>
            <Button onClick={() => setDialog({ open: true, contact: null })} data-testid="add-contact-button"><Plus className="mr-2 h-4 w-4" /> Add contact</Button>
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Input placeholder="Search company, name, email..." value={search} onChange={(e) => { setSearch(e.target.value); load(e.target.value); }} className="w-72" data-testid="contacts-search-input" />
          <Button variant="ghost" size="sm" onClick={exportTemplate} data-testid="download-template-button"><Download className="mr-1.5 h-4 w-4" /> CSV template</Button>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={selectWithoutApp} data-testid="select-without-app-button">
            Select all without application
          </Button>
          {selectedIds.size > 0 && (
            <Button size="sm" onClick={() => setBulkOpen(true)} data-testid="generate-selected-button">
              <Sparkles className="mr-1.5 h-3.5 w-3.5" /> Generate applications ({selectedIds.size})
            </Button>
          )}
        </div>
      </div>

      {selectedIds.size > 0 && (
        <div className="mb-4 flex items-center justify-between rounded-lg border bg-muted/40 px-3 py-2 text-sm">
          <span className="font-medium text-foreground">{selectedIds.size} of {contacts.length} contacts selected</span>
          <Button variant="ghost" size="sm" onClick={() => setSelectedIds(new Set())}>Clear selection</Button>
        </div>
      )}

      {contacts.length === 0 ? (
        <EmptyState
          icon={Users}
          title={search ? "No contacts match your search" : "No HR contacts yet"}
          description={search ? "Try a different search term." : "Import your HR contact list from a CSV/Excel file, or add contacts manually. Duplicate detection keeps your list clean."}
          testId="contacts-empty-state"
          actions={
            <>
              <Button variant="outline" onClick={() => setImportOpen(true)}><Upload className="mr-2 h-4 w-4" /> Import CSV/Excel</Button>
              <Button onClick={() => setDialog({ open: true, contact: null })}><Plus className="mr-2 h-4 w-4" /> Add manually</Button>
            </>
          }
        />
      ) : (
        <div className="rounded-xl border" data-testid="contacts-table">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <Checkbox checked={allVisibleSelected} onCheckedChange={toggleAllVisible} data-testid="select-all-visible-checkbox" />
                </TableHead>
                <TableHead>Company</TableHead>
                <TableHead>HR name</TableHead>
                <TableHead>HR email</TableHead>
                <TableHead>Job role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Last Contacted</TableHead>
                <TableHead>Source</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {contacts.map((c) => {
                const isSelected = selectedIds.has(c.id);
                return (
                  <TableRow key={c.id} data-testid="contact-row" className={isSelected ? "bg-muted/40" : ""}>
                    <TableCell>
                      <Checkbox checked={isSelected} onCheckedChange={() => toggleSelect(c.id)} data-testid={`select-contact-${c.id}`} />
                    </TableCell>
                    <TableCell className="font-medium">{c.company_name || "—"}</TableCell>
                    <TableCell>{c.hr_name || "—"}</TableCell>
                    <TableCell className="text-muted-foreground">{c.hr_email}</TableCell>
                    <TableCell>{c.job_role || "—"}</TableCell>
                    <TableCell><ContactStatusBadge status={c.application_status} /></TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {c.last_contacted_at ? new Date(c.last_contacted_at).toLocaleDateString() : "Never"}
                    </TableCell>
                    <TableCell>{c.application_source || "—"}</TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="ghost" onClick={() => setDialog({ open: true, contact: c })} data-testid={`edit-contact-${c.id}`}><Pencil className="h-4 w-4" /></Button>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button size="sm" variant="ghost" className="text-red-500" data-testid={`delete-contact-${c.id}`}><Trash2 className="h-4 w-4" /></Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader><AlertDialogTitle>Delete contact {c.hr_email}?</AlertDialogTitle><AlertDialogDescription>This cannot be undone. Existing applications keep their records.</AlertDialogDescription></AlertDialogHeader>
                          <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={() => remove(c)}>Delete</AlertDialogAction></AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <ContactDialog open={dialog.open} contact={dialog.contact} onClose={() => setDialog({ open: false, contact: null })} onSaved={() => load(search)} />
      <ImportDialog open={importOpen} onClose={() => setImportOpen(false)} onImported={() => load(search)} />
      <BulkGenerateDialog
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        selectedIds={Array.from(selectedIds)}
        onFinished={() => { load(search); setSelectedIds(new Set()); }}
      />
    </div>
  );
}
