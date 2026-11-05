import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Bell, Bot, Brain, CalendarClock, Mail, Save, Shield, Timer } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Loading, PageHeader } from "@/components/common";

const browserTz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

function DigestCard({ settings, set }) {
  const [sending, setSending] = useState(false);
  const d = settings.digest || {};
  const sendNow = async () => {
    setSending(true);
    try {
      const res = await api.post("/settings/digest/send-now");
      if (res.data.jobs) toast.success(`Digest with ${res.data.jobs} job${res.data.jobs === 1 ? "" : "s"} sent to ${res.data.sent_to}`);
      else toast.info("No board jobs are waiting for approval - nothing to send");
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not send digest"); }
    finally { setSending(false); }
  };
  return (
    <Card data-testid="settings-digest-card">
      <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Mail className="h-4 w-4 text-primary" /> Daily board digest</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <div><p className="text-sm font-medium">Morning email of new board jobs</p><p className="text-xs text-muted-foreground">Lists new matched job board applications waiting for your approval. Skipped on days with none.</p></div>
          <Switch checked={!!d.enabled} onCheckedChange={(v) => set("digest", "enabled", v)} data-testid="settings-digest-switch" />
        </div>
        <div className="space-y-1.5">
          <Label>Send at (hour, 0-23)</Label>
          <Input type="number" min="0" max="23" value={d.hour ?? 8} onChange={(e) => set("digest", "hour", e.target.value === "" ? "" : Math.min(23, Math.max(0, Math.round(Number(e.target.value)) || 0)))} data-testid="settings-digest-hour" />
          <p className="text-xs text-muted-foreground" data-testid="settings-digest-timezone">Your time zone: {browserTz()} (saved automatically)</p>
        </div>
        <Button variant="outline" size="sm" onClick={sendNow} disabled={sending} data-testid="digest-send-now-button">
          <Mail className="mr-2 h-3.5 w-3.5" /> {sending ? "Sending..." : "Send digest now"}
        </Button>
      </CardContent>
    </Card>
  );
}

export default function Settings() {
  const [settings, setSettings] = useState(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    api.get("/settings").then((r) => setSettings(r.data)).catch(() => toast.error("Could not load settings"));
  }, []);

  if (!settings) return <Loading />;

  const set = (section, key, value) => {
    if (section) setSettings({ ...settings, [section]: { ...settings[section], [key]: value } });
    else setSettings({ ...settings, [key]: value });
  };

  const save = async () => {
    setSaving(true);
    try {
      const res = await api.put("/settings", {
        ai_model: settings.ai_model,
        email_tone: settings.email_tone,
        autopilot: settings.autopilot,
        followups: settings.followups,
        interviews: settings.interviews,
        notifications: settings.notifications,
        digest: { enabled: !!settings.digest?.enabled, hour: settings.digest?.hour === "" ? 8 : Number(settings.digest?.hour ?? 8), timezone: browserTz() },
      });
      setSettings((prev) => ({ ...prev, ...res.data }));
      toast.success("Settings saved");
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not save settings"); }
    finally { setSaving(false); }
  };

  const testNotification = async () => {
    setTesting(true);
    try {
      const res = await api.post("/settings/notifications/test");
      toast.success(`Test notification sent to ${res.data.sent_to}`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Test failed"); }
    finally { setTesting(false); }
  };

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="AI provider, sending limits, auto-pilot preferences and notifications"
        actions={<Button onClick={save} disabled={saving} data-testid="save-settings-button"><Save className="mr-2 h-4 w-4" /> {saving ? "Saving..." : "Save all settings"}</Button>}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card data-testid="settings-ai-card">
          <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Brain className="h-4 w-4 text-primary" /> AI provider</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label>Model used for matching & email writing</Label>
              <Select value={settings.ai_model} onValueChange={(v) => set(null, "ai_model", v)} data-testid="settings-model-select">
                <SelectTrigger data-testid="settings-model-trigger"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(settings.models_available || []).map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">Powered by the Emergent Universal LLM key - no API key of your own needed.</p>
            </div>
            <div className="space-y-1.5">
              <Label>Default email tone</Label>
              <Select value={settings.email_tone} onValueChange={(v) => set(null, "email_tone", v)} data-testid="settings-tone-select">
                <SelectTrigger data-testid="settings-tone-trigger"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(settings.tones_available || []).map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        <Card data-testid="settings-autopilot-card">
          <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Bot className="h-4 w-4 text-primary" /> Auto-pilot preferences</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div><p className="text-sm font-medium">Auto-pilot enabled</p><p className="text-xs text-muted-foreground">Process the queue automatically on schedule</p></div>
              <Switch checked={!!settings.autopilot.enabled} onCheckedChange={(v) => set("autopilot", "enabled", v)} data-testid="settings-autopilot-switch" />
            </div>
            <div className="flex items-center justify-between">
              <div><p className="text-sm font-medium">Emergency paused</p><p className="text-xs text-muted-foreground">Blocks all automatic sending immediately</p></div>
              <Switch checked={!!settings.autopilot.paused} onCheckedChange={(v) => set("autopilot", "paused", v)} data-testid="settings-autopilot-paused-switch" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5"><Label>Daily email limit</Label><Input type="number" min="1" max="50" value={settings.autopilot.max_per_day} onChange={(e) => set("autopilot", "max_per_day", Number(e.target.value))} data-testid="settings-daily-limit" /></div>
              <div className="space-y-1.5"><Label>Min match score to auto-send</Label><Input type="number" min="0" max="100" value={settings.autopilot.min_match_score} onChange={(e) => set("autopilot", "min_match_score", Number(e.target.value))} data-testid="settings-min-score" /></div>
              <div className="space-y-1.5"><Label>Delay between sends (min)</Label><Input type="number" min="1" max="1440" value={settings.autopilot.min_delay_minutes} onChange={(e) => set("autopilot", "min_delay_minutes", Number(e.target.value))} data-testid="settings-delay" /></div>
              <div className="space-y-1.5"><Label>Retry limit</Label><Input type="number" min="0" max="5" value={settings.autopilot.max_retries} onChange={(e) => set("autopilot", "max_retries", Number(e.target.value))} data-testid="settings-retries" /></div>
            </div>
          </CardContent>
        </Card>

        <Card data-testid="settings-followups-card">
          <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Timer className="h-4 w-4 text-primary" /> Follow-up preferences</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div><p className="text-sm font-medium">Smart follow-up reminders</p><p className="text-xs text-muted-foreground">Draft a reminder when an application gets no reply. Always requires your approval before sending.</p></div>
              <Switch checked={!!settings.followups.enabled} onCheckedChange={(v) => set("followups", "enabled", v)} data-testid="settings-followups-switch" />
            </div>
            <div className="space-y-1.5">
              <Label>Wait days before follow-up</Label>
              <Input type="number" min="1" max="30" value={settings.followups.days} onChange={(e) => set("followups", "days", Number(e.target.value))} data-testid="settings-followup-days" />
            </div>
          </CardContent>
        </Card>

        <Card data-testid="settings-notifications-card">
          <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Bell className="h-4 w-4 text-primary" /> Notifications</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {[["application_sent", "Application sent confirmations"], ["reply_received", "HR reply alerts"], ["followup_ready", "Follow-up ready reminders"], ["send_failed", "Send failure alerts"], ["interview_reminder", "Interview reminders"]].map(([key, label]) => (
              <div key={key} className="flex items-center justify-between">
                <p className="text-sm">{label}</p>
                <Switch checked={!!settings.notifications[key]} onCheckedChange={(v) => set("notifications", key, v)} data-testid={`settings-notif-${key}`} />
              </div>
            ))}
            <p className="text-xs text-muted-foreground">Emails go to {settings.user?.email || "your account email"} via the managed sender.</p>
            <Button variant="outline" size="sm" onClick={testNotification} disabled={testing} data-testid="test-notification-button">
              <Bell className="mr-2 h-3.5 w-3.5" /> {testing ? "Sending..." : "Send test notification"}
            </Button>
          </CardContent>
        </Card>

        <Card data-testid="settings-interviews-card">
          <CardHeader><CardTitle className="flex items-center gap-2 text-base"><CalendarClock className="h-4 w-4 text-primary" /> Interview reminders</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label>Remind me this many hours before each interview</Label>
              <Input type="number" min="1" max="168" value={settings.interviews?.reminder_hours ?? 24} onChange={(e) => set("interviews", "reminder_hours", Number(e.target.value))} data-testid="settings-interview-reminder-hours" />
            </div>
            <p className="text-xs text-muted-foreground">Schedule interviews from the Application Tracker when an HR marks you as interview-stage.</p>
          </CardContent>
        </Card>

        <DigestCard settings={settings} set={set} />

        <Card className="lg:col-span-2" data-testid="settings-security-card">
          <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Shield className="h-4 w-4 text-primary" /> Account & security</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-3 text-sm">
            <div><p className="text-muted-foreground">Signed in as</p><p className="font-medium" data-testid="settings-user-email">{settings.user?.email || "—"}</p></div>
            <div><p className="text-muted-foreground">Authentication</p><p className="font-medium">Managed sign-in (email + password)</p></div>
            <div><p className="text-muted-foreground">Data isolation</p><p className="font-medium">All records scoped to your account only</p></div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
