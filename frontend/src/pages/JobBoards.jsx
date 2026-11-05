import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Loading, PageHeader } from "@/components/common";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ExtensionSetup } from "@/components/boards/ExtensionSetup";
import { ApplyProfileForm } from "@/components/boards/ApplyProfileForm";
import { BoardSearch } from "@/components/boards/BoardSearch";
import { BoardApplications } from "@/components/boards/BoardApplications";

function ModeNote({ autopilot, sentToday }) {
  if (!autopilot) return null;
  const auto = autopilot.enabled && autopilot.mode === "auto" && !autopilot.paused;
  return (
    <Alert className="mb-6" data-testid="boards-mode-note">
      <AlertDescription className="text-sm">
        {autopilot.paused
          ? "Emergency stop is active - the browser helper will not submit anything until you resume Auto-Pilot."
          : auto
            ? `Auto-apply is on: jobs scoring ${autopilot.min_match_score}%+ are submitted automatically by the browser helper (up to ${autopilot.max_per_day}/day, ${sentToday} used today). Other jobs wait for your approval.`
            : "Approval mode: every board application waits for your approval below before the browser helper submits it."}{" "}
        <Link to="/queue" className="underline" data-testid="boards-mode-link">Change in Application Queue</Link>
      </AlertDescription>
    </Alert>
  );
}

export default function JobBoards() {
  const [data, setData] = useState(null);
  const load = useCallback(async () => {
    try {
      const res = await api.get("/boards/overview");
      setData(res.data);
    } catch {
      setData((d) => (d && !d.error ? d : { error: true }));
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  if (!data) return <Loading />;
  if (data.error) {
    return (
      <Alert data-testid="boards-load-error">
        <AlertDescription>Could not load job boards. <button className="underline" onClick={() => { setData(null); load(); }}>Try again</button></AlertDescription>
      </Alert>
    );
  }
  return (
    <div data-testid="job-boards-page">
      <PageHeader
        title="Job Boards Auto-Apply"
        subtitle="Find and apply to jobs on LinkedIn, Naukri, Indeed, Internshala, Wellfound, Instahyre and other boards"
      />
      <ModeNote autopilot={data.autopilot} sentToday={data.sent_today} />
      <Tabs defaultValue="applications">
        <TabsList className="mb-6 flex h-auto flex-wrap">
          <TabsTrigger value="applications" data-testid="boards-tab-applications">Board applications</TabsTrigger>
          <TabsTrigger value="search" data-testid="boards-tab-search">Automatic search</TabsTrigger>
          <TabsTrigger value="helper" data-testid="boards-tab-helper">Browser helper</TabsTrigger>
          <TabsTrigger value="profile" data-testid="boards-tab-profile">Application answers</TabsTrigger>
        </TabsList>
        <TabsContent value="applications">
          <BoardApplications apps={data.applications || []} boards={data.boards || {}} onChanged={load} />
        </TabsContent>
        <TabsContent value="search">
          <BoardSearch config={data.board_search} boards={data.boards || {}} runs={data.runs || []} onChanged={load} />
        </TabsContent>
        <TabsContent value="helper">
          <ExtensionSetup extension={data.extension} onChanged={load} />
        </TabsContent>
        <TabsContent value="profile">
          <ApplyProfileForm profile={data.apply_profile || {}} onChanged={load} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
