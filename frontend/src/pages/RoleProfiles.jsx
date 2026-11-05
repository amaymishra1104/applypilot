import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Download, Eye, FileText, FolderOpen, History, Pencil, Plus, RotateCcw, Star, Trash2, Upload } from "lucide-react";
import { api, downloadFile, fetchBlobUrl } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, Loading, PageHeader } from "@/components/common";

const EMPTY_ROLES_MESSAGE =
  "No role profiles created yet. Create your first role profile and upload its resume.";

function RoleDialog({ open, onClose, role, onSaved }) {
  const [form, setForm] = useState({ title: "", description: "", skills: "", experience_required: "", notes: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setForm(role
        ? { title: role.title, description: role.description, skills: (role.skills || []).join(", "), experience_required: role.experience_required || "", notes: role.notes || "" }
        : { title: "", description: "", skills: "", experience_required: "", notes: "" });
    }
  }, [open, role]);

  const submit = async () => {
    if (!form.title.trim()) return toast.error("Role title is required");
    setBusy(true);
    try {
      const payload = {
        title: form.title,
        description: form.description,
        skills: form.skills.split(",").map((s) => s.trim()).filter(Boolean),
        experience_required: form.experience_required,
        notes: form.notes,
      };
      const res = role ? await api.put(`/roles/${role.id}`, payload) : await api.post("/roles", payload);
      toast.success(role ? "Role profile updated" : "Role profile created");
      onSaved(res.data);
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not save role profile");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg" data-testid="role-dialog">
        <DialogHeader>
          <DialogTitle>{role ? "Edit role profile" : "Create new role profile"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Job title *</Label>
            <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="e.g. Senior Backend Engineer" data-testid="role-title-input" />
          </div>
          <div className="space-y-1.5">
            <Label>Role description</Label>
            <Textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="What kind of jobs does this profile target?" data-testid="role-description-input" />
          </div>
          <div className="space-y-1.5">
            <Label>Required skills & keywords (comma separated)</Label>
            <Input value={form.skills} onChange={(e) => setForm({ ...form, skills: e.target.value })} placeholder="Python, FastAPI, AWS, Docker" data-testid="role-skills-input" />
          </div>
          <div className="space-y-1.5">
            <Label>Experience requirements (optional)</Label>
            <Input value={form.experience_required} onChange={(e) => setForm({ ...form, experience_required: e.target.value })} placeholder="e.g. 3+ years" data-testid="role-experience-input" />
          </div>
          <div className="space-y-1.5">
            <Label>Personal notes (optional)</Label>
            <Textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Anything to remember about this profile" data-testid="role-notes-input" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} data-testid="role-cancel-button">Cancel</Button>
          <Button onClick={submit} disabled={busy} data-testid="role-save-button">{busy ? "Saving..." : role ? "Save changes" : "Create role"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function UploadDialog({ open, onClose, role, onUploaded }) {
  const [name, setName] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);

  useEffect(() => {
    if (open) { setName(""); setFile(null); }
  }, [open, role]);

  const submit = async () => {
    if (!file) return toast.error("Choose a PDF file first");
    if (!file.name.toLowerCase().endsWith(".pdf")) return toast.error("Only PDF files are allowed");
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("name", name || file.name.replace(/\.pdf$/i, ""));
      const res = await api.post(`/roles/${role.id}/resumes`, fd);
      if (res.data?.warning) {
        toast.warning(res.data.warning, { duration: 7000 });
      } else {
        toast.success(`Resume uploaded as version ${res.data.active_resume?.version_no || ""} (now active)`);
      }
      onUploaded(res.data);
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md" data-testid="upload-dialog">
        <DialogHeader><DialogTitle>Upload resume for "{role?.title}"</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Resume name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Backend-2026-v2" data-testid="resume-name-input" />
          </div>
          <div className="space-y-1.5">
            <Label>PDF file (max 5 MB)</Label>
            <Input type="file" accept="application/pdf,.pdf" ref={fileRef} onChange={(e) => setFile(e.target.files?.[0] || null)} data-testid="resume-file-input" />
            {file && <p className="text-xs text-muted-foreground">{file.name} ({Math.round(file.size / 1024)} KB)</p>}
          </div>
          <p className="text-xs text-muted-foreground">A new version is created and marked active automatically. Previous versions stay available.</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={busy} data-testid="resume-upload-confirm">{busy ? "Uploading..." : "Upload & activate"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function VersionsSheet({ role, open, onClose, onChanged }) {
  const [versions, setVersions] = useState([]);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!role) return;
    setLoading(true);
    try {
      const res = await api.get(`/roles/${role.id}/resumes`);
      setVersions(res.data);
    } catch {
      toast.error("Could not load resume versions");
    } finally {
      setLoading(false);
    }
  }, [role]);

  useEffect(() => { if (open) load(); }, [open, load]);
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  const activate = async (v) => {
    try {
      await api.put(`/roles/${role.id}/resumes/${v.id}/activate`);
      toast.success(`Version ${v.version_no} is now active`);
      load(); onChanged();
    } catch { toast.error("Could not activate version"); }
  };

  const remove = async (v) => {
    try {
      await api.delete(`/roles/${role.id}/resumes/${v.id}`);
      toast.success(`Version ${v.version_no} deleted`);
      load(); onChanged();
    } catch { toast.error("Could not delete version"); }
  };

  const preview = async (v) => {
    try {
      const url = await fetchBlobUrl(`/resumes/${v.id}/preview`);
      setPreviewUrl(url);
    } catch { toast.error("Could not load preview"); }
  };

  return (
    <>
      <Sheet open={open} onOpenChange={(v) => !v && onClose()}>
        <SheetContent side="right" className="w-full max-w-md overflow-y-auto sm:max-w-lg" data-testid="versions-sheet">
          <SheetHeader>
            <SheetTitle>Resume versions — {role?.title}</SheetTitle>
          </SheetHeader>
          <div className="px-4 pb-8">
            <Button size="sm" className="mb-4" onClick={() => onChanged("upload")} data-testid="versions-upload-button">
              <Plus className="mr-1.5 h-4 w-4" /> Upload new version
            </Button>
            {loading ? <Loading /> : versions.length === 0 ? (
              <p className="text-sm text-muted-foreground">No resume versions yet.</p>
            ) : (
              <ul className="space-y-3" data-testid="versions-list">
                {versions.map((v) => (
                  <li key={v.id} className="rounded-lg border p-3" data-testid="version-item">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{v.name}</p>
                        <p className="text-xs text-muted-foreground">v{v.version_no} · {Math.round(v.size / 1024)} KB · {new Date(v.created_at).toLocaleDateString()}</p>
                      </div>
                      {v.active ? <Badge className="bg-primary/15 text-primary border-primary/30">Active</Badge> : null}
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {!v.active && <Button size="sm" variant="outline" onClick={() => activate(v)} data-testid={`activate-version-${v.version_no}`}><Star className="mr-1 h-3.5 w-3.5" /> Set active</Button>}
                      <Button size="sm" variant="outline" onClick={() => preview(v)} data-testid={`preview-version-${v.version_no}`}><Eye className="mr-1 h-3.5 w-3.5" /> View</Button>
                      <Button size="sm" variant="outline" onClick={() => downloadFile(`/resumes/${v.id}/download`, v.filename || `${v.name}.pdf`)} data-testid={`download-version-${v.version_no}`}><Download className="mr-1 h-3.5 w-3.5" /> Download</Button>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button size="sm" variant="outline" className="text-red-500" data-testid={`delete-version-${v.version_no}`}><Trash2 className="mr-1 h-3.5 w-3.5" /> Delete</Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader><AlertDialogTitle>Delete resume version {v.version_no}?</AlertDialogTitle>
                            <AlertDialogDescription>Previously sent applications keep their original attachment. This version will no longer be selectable for new applications.</AlertDialogDescription></AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancel</AlertDialogCancel>
                            <AlertDialogAction onClick={() => remove(v)} data-testid="confirm-delete-version">Delete</AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </SheetContent>
      </Sheet>
      <Dialog open={!!previewUrl} onOpenChange={(v) => !v && setPreviewUrl(null)}>
        <DialogContent className="max-w-3xl h-[80vh]" data-testid="resume-preview-dialog">
          <DialogHeader><DialogTitle>Resume preview</DialogTitle></DialogHeader>
          {previewUrl && <iframe src={previewUrl} title="Resume preview" className="h-[calc(80vh-5rem)] w-full rounded-md border" />}
        </DialogContent>
      </Dialog>
    </>
  );
}

export default function RoleProfiles() {
  const [roles, setRoles] = useState(null);
  const [roleDialog, setRoleDialog] = useState({ open: false, role: null });
  const [uploadFor, setUploadFor] = useState(null);
  const [versionsFor, setVersionsFor] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await api.get("/roles");
      setRoles(res.data);
    } catch {
      toast.error("Could not load role profiles");
      setRoles([]);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const removeRole = async (role) => {
    try {
      await api.delete(`/roles/${role.id}`);
      toast.success(`Role "${role.title}" deleted`);
      load();
    } catch { toast.error("Could not delete role"); }
  };

  if (roles === null) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Resume & Role Profiles"
        subtitle="Create custom role profiles and manage an independent, versioned resume for each one"
        actions={
          <>
            <Button onClick={() => setRoleDialog({ open: true, role: null })} data-testid="create-role-button">
              <Plus className="mr-2 h-4 w-4" /> Create New Role
            </Button>
          </>
        }
      />

      {roles.length === 0 ? (
        <EmptyState
          icon={FolderOpen}
          title={EMPTY_ROLES_MESSAGE}
          description="Every application uses the resume you attach to a role profile. Nothing is pre-created - you control all roles and resumes."
          testId="roles-empty-state"
          actions={
            <Button onClick={() => setRoleDialog({ open: true, role: null })} data-testid="empty-create-role-button">
              <Plus className="mr-2 h-4 w-4" /> Create your first role profile
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3" data-testid="roles-grid">
          {roles.map((role) => (
            <Card key={role.id} className="flex flex-col" data-testid="role-card">
              <CardContent className="flex flex-1 flex-col gap-3 p-5">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h3 className="font-display text-lg font-semibold" data-testid="role-card-title">{role.title}</h3>
                    {role.experience_required && <p className="text-xs text-muted-foreground">{role.experience_required}</p>}
                  </div>
                  <Badge variant="outline">{role.version_count} {role.version_count === 1 ? "version" : "versions"}</Badge>
                </div>
                {role.description && <p className="line-clamp-2 text-sm text-muted-foreground">{role.description}</p>}
                {!!role.skills.length && (
                  <div className="flex flex-wrap gap-1.5" data-testid="role-card-skills">
                    {role.skills.slice(0, 6).map((s) => (
                      <Badge key={s} variant="secondary" className="text-xs font-normal">{s}</Badge>
                    ))}
                    {role.skills.length > 6 && <Badge variant="secondary" className="text-xs font-normal">+{role.skills.length - 6}</Badge>}
                  </div>
                )}
                <div className="mt-auto rounded-lg border bg-muted/40 p-3" data-testid="role-card-active-resume">
                  {role.active_resume ? (
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-primary" />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{role.active_resume.name}</p>
                        <p className="text-xs text-muted-foreground">Active · v{role.active_resume.version_no} · {Math.round(role.active_resume.size / 1024)} KB</p>
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm text-amber-600 dark:text-amber-400">No resume uploaded yet</p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => setUploadFor(role)} disabled={!role.active_resume && false} data-testid={`upload-resume-${role.id}`}>
                    <Upload className="mr-1.5 h-3.5 w-3.5" /> {role.active_resume ? "Replace resume" : "Upload resume"}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setVersionsFor(role)} data-testid={`view-versions-${role.id}`}>
                    <History className="mr-1.5 h-3.5 w-3.5" /> Versions
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setRoleDialog({ open: true, role })} data-testid={`edit-role-${role.id}`}>
                    <Pencil className="mr-1.5 h-3.5 w-3.5" /> Edit
                  </Button>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button size="sm" variant="outline" className="text-red-500" data-testid={`delete-role-${role.id}`}>
                        <Trash2 className="mr-1.5 h-3.5 w-3.5" /> Delete
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader><AlertDialogTitle>Delete role profile "{role.title}"?</AlertDialogTitle>
                        <AlertDialogDescription>This removes the role and all of its resume versions. Previously sent applications keep their historical records and attachments.</AlertDialogDescription></AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={() => removeRole(role)} data-testid="confirm-delete-role">Delete</AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <RoleDialog open={roleDialog.open} role={roleDialog.role} onClose={() => setRoleDialog({ open: false, role: null })} onSaved={load} />
      <UploadDialog open={!!uploadFor} role={uploadFor} onClose={() => setUploadFor(null)} onUploaded={load} />
      <VersionsSheet
        role={versionsFor}
        open={!!versionsFor}
        onClose={() => setVersionsFor(null)}
        onChanged={(action) => { if (action === "upload") { setUploadFor(versionsFor); setVersionsFor(null); } else load(); }}
      />
    </div>
  );
}
