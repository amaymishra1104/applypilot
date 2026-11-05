import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { CheckCircle2, Copy, KeyRound, Link2, Mail, Plug, Unplug } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loading, PageHeader } from "@/components/common";

export default function GmailPage() {
  const [status, setStatus] = useState(null);
  const [creds, setCreds] = useState({ client_id: "", client_secret: "" });
  const [connecting, setConnecting] = useState(false);
  const [savingCreds, setSavingCreds] = useState(false);
  const [params, setParams] = useSearchParams();

  const load = async () => {
    try { setStatus((await api.get("/gmail/status")).data); }
    catch { toast.error("Could not load Gmail status"); }
  };
  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (params.get("connected")) {
      toast.success("Gmail connected - applications can now be sent from your account");
      setParams({}, { replace: true });
    }
    if (params.get("error")) {
      toast.error(`Gmail connection failed: ${params.get("error")}`);
      setParams({}, { replace: true });
    }
  }, [params, setParams]);

  const connect = async () => {
    setConnecting(true);
    try {
      const res = await api.post("/gmail/start", { frontend_origin: window.location.origin });
      window.location.href = res.data.auth_url;
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail === "google_not_configured") {
        toast.error("Add your Google OAuth client ID and secret first (form below)");
      } else toast.error(detail || "Could not start Google sign-in");
      setConnecting(false);
    }
  };

  const disconnect = async () => {
    try {
      await api.post("/gmail/disconnect");
      toast.success("Gmail disconnected");
      load();
    } catch { toast.error("Could not disconnect"); }
  };

  const saveCreds = async () => {
    if (!creds.client_id.trim() || !creds.client_secret.trim()) return toast.error("Both fields are required");
    setSavingCreds(true);
    try {
      await api.post("/settings/google-oauth", creds);
      toast.success("Google OAuth credentials saved (encrypted)");
      setCreds({ client_id: "", client_secret: "" });
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save credentials"); }
    finally { setSavingCreds(false); }
  };

  if (!status) return <Loading />;

  return (
    <div>
      <PageHeader title="Gmail Integration" subtitle="Connect Gmail to send applications from your own account and detect HR replies" />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card data-testid="gmail-status-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base"><Mail className="h-4 w-4 text-primary" /> Connection status</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {status.connected ? (
              <div className="space-y-3" data-testid="gmail-connected-panel">
                <p className="flex items-center gap-2 text-sm">
                  <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                  Connected as <strong>{status.email}</strong>
                </p>
                <p className="text-xs text-muted-foreground">Since {new Date(status.connected_at).toLocaleString()}</p>
                <p className="text-xs text-muted-foreground">Scopes: {status.scopes?.length} minimal Gmail scopes</p>
                <Button variant="outline" onClick={disconnect} className="text-red-500 border-red-500/30" data-testid="gmail-disconnect-button">
                  <Unplug className="mr-2 h-4 w-4" /> Disconnect
                </Button>
              </div>
            ) : (
              <div className="space-y-3" data-testid="gmail-connect-panel">
                <p className="text-sm text-muted-foreground">
                  Connect your Gmail account with OAuth 2.0 - we never see or store your password.
                  Application emails are sent from your own address with your resume attached.
                </p>
                <Button onClick={connect} disabled={connecting} data-testid="gmail-connect-button">
                  <Plug className="mr-2 h-4 w-4" /> {connecting ? "Redirecting to Google..." : "Connect Gmail"}
                </Button>
                {!status.google_configured && (
                  <p className="text-xs text-amber-600 dark:text-amber-400">
                    Google OAuth credentials are not configured yet - add them in the panel on the right.
                  </p>
                )}
              </div>
            )}
            <div className="rounded-lg border bg-muted/40 p-3 text-xs text-muted-foreground" data-testid="redirect-uri-box">
              <p className="flex items-center gap-1.5 font-medium text-foreground"><Link2 className="h-3.5 w-3.5" /> Authorized redirect URI for Google Cloud</p>
              <div className="mt-1.5 flex items-center gap-2">
                <code className="flex-1 truncate rounded bg-background px-2 py-1">{status.redirect_uri}</code>
                <Button size="sm" variant="ghost" onClick={() => { navigator.clipboard.writeText(status.redirect_uri); toast.success("Copied"); }} data-testid="copy-redirect-uri">
                  <Copy className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card data-testid="gmail-creds-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base"><KeyRound className="h-4 w-4 text-primary" /> Google OAuth credentials</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {status.google_configured ? (
                <p className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400" data-testid="google-configured">
                  <CheckCircle2 className="h-4 w-4" /> Credentials configured {status.connected ? "" : "- you can connect now"}
                </p>
              ) : (
                <>
                  <p className="text-sm text-muted-foreground">
                    Create a Google Cloud project, enable the Gmail API, create an OAuth "Web application" client,
                    and paste its ID and secret here. They are stored encrypted and never leave the backend.
                  </p>
                  <div className="space-y-1.5">
                    <Label>Client ID</Label>
                    <Input value={creds.client_id} onChange={(e) => setCreds({ ...creds, client_id: e.target.value })} placeholder="xxxx.apps.googleusercontent.com" data-testid="google-client-id-input" />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Client secret</Label>
                    <Input type="password" value={creds.client_secret} onChange={(e) => setCreds({ ...creds, client_secret: e.target.value })} data-testid="google-client-secret-input" />
                  </div>
                  <Button onClick={saveCreds} disabled={savingCreds} data-testid="save-google-creds">{savingCreds ? "Saving..." : "Save credentials"}</Button>
                </>
              )}
            </CardContent>
          </Card>

          <Card data-testid="gmail-setup-card">
            <CardHeader><CardTitle className="text-base">Google Cloud setup steps</CardTitle></CardHeader>
            <CardContent>
              <ol className="list-decimal space-y-2 pl-4 text-sm text-muted-foreground" data-testid="gmail-setup-steps">
                <li>Go to <span className="text-foreground">console.cloud.google.com</span> and create a project.</li>
                <li>Enable the <span className="text-foreground">Gmail API</span> under APIs &amp; Services.</li>
                <li>Configure the OAuth consent screen (External, add yourself as a test user).</li>
                <li>Create credentials → OAuth client ID → Web application.</li>
                <li>Add this app's origin as an authorized JavaScript origin, and the redirect URI shown on the left.</li>
                <li>Paste the client ID and secret here and click Connect Gmail.</li>
              </ol>
              <div className="mt-4 flex flex-wrap gap-2">
                <Badge variant="outline">gmail.readonly</Badge>
                <Badge variant="outline">gmail.modify</Badge>
                <Badge variant="outline">gmail.labels</Badge>
                <Badge variant="outline">userinfo.email</Badge>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
