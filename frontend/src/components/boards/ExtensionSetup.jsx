import { useState } from "react";
import { toast } from "sonner";
import { Copy, Download, KeyRound, ShieldOff } from "lucide-react";
import { api, BACKEND_URL } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const STEPS = [
  "Download the helper and unzip it.",
  "Open chrome://extensions, turn on Developer mode, click Load unpacked and pick the unzipped folder.",
  "Create a connection code below and paste it into the helper popup.",
  "Stay logged in to your job boards in Chrome as usual - ApplyPilot never asks for your board passwords.",
  "On any job page click Save job; click Autofill to fill the form; turn on Auto-apply in the popup to let it submit approved jobs for you.",
];

function ConnectionCode({ code }) {
  const copy = async () => {
    await navigator.clipboard.writeText(code);
    toast.success("Connection code copied");
  };
  return (
    <div className="space-y-2" data-testid="connection-code-box">
      <p className="text-sm text-muted-foreground">Copy this now - it is shown only once.</p>
      <div className="flex gap-2">
        <Input readOnly value={code} className="font-mono text-xs" data-testid="connection-code-input" />
        <Button variant="outline" onClick={copy} data-testid="copy-connection-code"><Copy className="h-4 w-4" /></Button>
      </div>
    </div>
  );
}

export function ExtensionSetup({ extension, onChanged }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      const res = await api.post("/boards/extension-token");
      setCode(btoa(JSON.stringify({ u: BACKEND_URL, t: res.data.token })));
      onChanged();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not create a connection code");
    } finally {
      setBusy(false);
    }
  };
  const revoke = async () => {
    try {
      await api.delete("/boards/extension-token");
      setCode("");
      toast.success("Browser helper disconnected");
      onChanged();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not disconnect");
    }
  };
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle className="text-lg">Install the ApplyPilot browser helper</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground">
            {STEPS.map((s) => <li key={s}>{s}</li>)}
          </ol>
          <Button asChild data-testid="download-extension-button">
            <a href="/applypilot-extension.zip" download><Download className="mr-2 h-4 w-4" /> Download helper (Chrome)</a>
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-lg">Connection</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm" data-testid="extension-status">
            {extension
              ? `Connected code created ${new Date(extension.created_at).toLocaleString()} - ${extension.last_used_at ? `last used ${new Date(extension.last_used_at).toLocaleString()}` : "not used yet"}`
              : "No helper connected yet."}
          </p>
          {code && <ConnectionCode code={code} />}
          <div className="flex flex-wrap gap-2">
            <Button onClick={create} disabled={busy} data-testid="create-connection-code">
              <KeyRound className="mr-2 h-4 w-4" /> {extension ? "Create new code" : "Create connection code"}
            </Button>
            {extension && (
              <Button variant="outline" onClick={revoke} data-testid="revoke-connection-code">
                <ShieldOff className="mr-2 h-4 w-4" /> Disconnect
              </Button>
            )}
          </div>
          <p className="text-xs text-muted-foreground">Creating a new code disconnects any older one.</p>
        </CardContent>
      </Card>
    </div>
  );
}
