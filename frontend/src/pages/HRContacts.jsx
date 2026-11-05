import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Download, Pencil, Plus, Trash2, Upload, Users } from "lucide-react";
import { api, downloadFile } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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

export default function HRContacts() {
  const [contacts, setContacts] = useState(null);
  const [search, setSearch] = useState("");
  const [dialog, setDialog] = useState({ open: false, contact: null });
  const [importOpen, setImportOpen] = useState(false);

  const load = useCallback(async (q = "") => {
    try {
      const res = await api.get(`/contacts${q ? `?search=${encodeURIComponent(q)}` : ""}`);
      setContacts(res.data);
    } catch { toast.error("Could not load contacts"); setContacts([]); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const remove = async (c) => {
    try { await api.delete(`/contacts/${c.id}`); toast.success("Contact deleted"); load(search); }
    catch { toast.error("Could not delete contact"); }
  };

  const exportTemplate = () => {
    const csv = "company_name,hr_name,hr_email,company_website,job_role,job_description,application_source,notes\n";
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "hr-contacts-template.csv"; a.click();
    URL.revokeObjectURL(url);
  };

  if (contacts === null) return <Loading />;

  return (
    <div>
      <PageHeader
        title="HR Contacts"
        subtitle="Your recruiter and HR network - import or add manually"
        actions={
          <>
            <Button variant="outline" onClick={() => setImportOpen(true)} data-testid="import-contacts-button"><Upload className="mr-2 h-4 w-4" /> Import CSV/Excel</Button>
            <Button onClick={() => setDialog({ open: true, contact: null })} data-testid="add-contact-button"><Plus className="mr-2 h-4 w-4" /> Add contact</Button>
          </>
        }
      />

      <div className="mb-4 flex items-center gap-3">
        <Input placeholder="Search company, name, email..." value={search} onChange={(e) => { setSearch(e.target.value); load(e.target.value); }} className="max-w-sm" data-testid="contacts-search-input" />
        <Button variant="ghost" size="sm" onClick={exportTemplate} data-testid="download-template-button"><Download className="mr-1.5 h-4 w-4" /> CSV template</Button>
      </div>

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
                <TableHead>Company</TableHead>
                <TableHead>HR name</TableHead>
                <TableHead>HR email</TableHead>
                <TableHead>Job role</TableHead>
                <TableHead>Source</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {contacts.map((c) => (
                <TableRow key={c.id} data-testid="contact-row">
                  <TableCell className="font-medium">{c.company_name || "—"}</TableCell>
                  <TableCell>{c.hr_name || "—"}</TableCell>
                  <TableCell className="text-muted-foreground">{c.hr_email}</TableCell>
                  <TableCell>{c.job_role || "—"}</TableCell>
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
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <ContactDialog open={dialog.open} contact={dialog.contact} onClose={() => setDialog({ open: false, contact: null })} onSaved={() => load(search)} />
      <ImportDialog open={importOpen} onClose={() => setImportOpen(false)} onImported={() => load(search)} />
    </div>
  );
}
