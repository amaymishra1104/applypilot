import { useState } from "react";
import { toast } from "sonner";
import { Play, Save } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

function RunHistory({ runs, boards }) {
  if (!runs.length) return <p className="text-sm text-muted-foreground" data-testid="search-runs-empty">No searches run yet.</p>;
  return (
    <div className="space-y-3" data-testid="search-runs">
      {runs.map((r) => (
        <div key={r.id} className="rounded-lg border p-3 text-sm" data-testid="search-run-item">
          <p className="font-medium">
            {new Date(r.started_at).toLocaleString()} · {r.status === "running" ? "Running..." : `${r.new_jobs} new jobs, ${r.applications_created} applications prepared`}
          </p>
          <ul className="mt-2 space-y-1 text-muted-foreground">
            {Object.entries(r.boards || {}).map(([b, s]) => (
              <li key={b} data-testid={`search-run-board-${b}`}>
                {boards[b]?.label || b}: {s.found} found, {s.new} new{s.error ? ` - ${s.error}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function BoardSearch({ config, boards, runs, onChanged }) {
  const [cfg, setCfg] = useState({ ...config, keywordsText: (config.keywords || []).join(", ") });
  const [busy, setBusy] = useState(false);
  const searchable = Object.entries(boards).filter(([, b]) => b.search);
  const toggleBoard = (b) => setCfg((c) => ({ ...c, boards: c.boards.includes(b) ? c.boards.filter((x) => x !== b) : [...c.boards, b] }));
  const payload = () => ({ enabled: cfg.enabled, location: cfg.location, boards: cfg.boards,
    max_new_per_run: Number(cfg.max_new_per_run) || 10, keywords: cfg.keywordsText.split(",").map((k) => k.trim()).filter(Boolean) });
  const save = async () => {
    setBusy(true);
    try {
      await api.put("/boards/search-config", payload());
      toast.success("Search settings saved");
      onChanged();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not save");
    } finally {
      setBusy(false);
    }
  };
  const run = async () => {
    setBusy(true);
    try {
      await api.put("/boards/search-config", payload());
      await api.post("/boards/search/run");
      toast.success("Search started - results appear below in a minute or two");
      setTimeout(onChanged, 2000);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not start search");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
      <Card>
        <CardHeader><CardTitle className="text-lg">Search boards by your role keywords</CardTitle></CardHeader>
        <CardContent className="space-y-5">
          <div className="flex items-center justify-between rounded-lg border p-3">
            <div>
              <p className="text-sm font-medium">Search automatically every 6 hours</p>
              <p className="text-xs text-muted-foreground">New matching jobs become board applications that follow your apply mode.</p>
            </div>
            <Switch checked={!!cfg.enabled} onCheckedChange={(v) => setCfg((c) => ({ ...c, enabled: v }))} data-testid="search-enabled-switch" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="kw">Keywords (comma separated)</Label>
            <Input id="kw" placeholder="Leave empty to use your role profile titles" value={cfg.keywordsText}
              onChange={(e) => setCfg((c) => ({ ...c, keywordsText: e.target.value }))} data-testid="search-keywords-input" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="loc">Location</Label>
              <Input id="loc" value={cfg.location} onChange={(e) => setCfg((c) => ({ ...c, location: e.target.value }))} data-testid="search-location-input" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="max">Max new jobs per search (1-25)</Label>
              <Input id="max" type="number" min={1} max={25} value={cfg.max_new_per_run}
                onChange={(e) => setCfg((c) => ({ ...c, max_new_per_run: e.target.value }))} data-testid="search-max-input" />
            </div>
          </div>
          <div className="space-y-2">
            <Label>Boards</Label>
            <div className="grid gap-2 sm:grid-cols-2">
              {searchable.map(([key, b]) => (
                <label key={key} className="flex items-center gap-2 rounded-md border p-2 text-sm">
                  <Checkbox checked={cfg.boards.includes(key)} onCheckedChange={() => toggleBoard(key)} data-testid={`search-board-${key}`} />
                  {b.label}
                </label>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">Naukri and Indeed often block automated search; when they do, the result below says so and you can save their jobs with the browser helper instead.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={save} disabled={busy} data-testid="save-search-config"><Save className="mr-2 h-4 w-4" /> Save</Button>
            <Button onClick={run} disabled={busy || !cfg.boards.length} data-testid="run-search-now"><Play className="mr-2 h-4 w-4" /> Search now</Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-lg">Recent searches</CardTitle>
          <Button size="sm" variant="ghost" onClick={onChanged} data-testid="refresh-search-runs">Refresh</Button>
        </CardHeader>
        <CardContent><RunHistory runs={runs} boards={boards} /></CardContent>
      </Card>
    </div>
  );
}
