import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { BarChart3, Briefcase, CalendarClock, CheckCircle2, FileText, Mail, TrendingUp, Users } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EmptyState, Loading, PageHeader, StatCard, StatusBadge } from "@/components/common";
import { STATUS_META } from "@/components/common";

const EVENT_ICONS = {
  draft_created: FileText,
  application_sent: Mail,
  reply_received: CheckCircle2,
  followup_draft_created: TrendingUp,
  followup_sent: Mail,
  approved: CheckCircle2,
  send_failed: Briefcase,
  status_changed: BarChart3,
  autopilot_paused: Briefcase,
};

const PIE_COLORS = ["#0D9488", "#3B82F6", "#F59E0B", "#8B5CF6", "#10B981", "#EF4444", "#64748B", "#6366F1", "#84CC16"];

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/dashboard").then((r) => setData(r.data)).catch(() => toast.error("Could not load dashboard")).finally(() => setLoading(false));
  }, []);

  if (loading) return <Loading />;
  if (!data) return null;

  const { stats, counters } = data;
  const isEmpty = stats.total_applications === 0 && counters.opportunities === 0 && counters.role_profiles === 0;

  const steps = [
    { done: counters.role_profiles > 0, label: "Create a role profile & upload its resume", to: "/resumes", testId: "step-roles" },
    { done: counters.hr_contacts > 0, label: "Import HR contacts (CSV/Excel or manual)", to: "/contacts", testId: "step-contacts" },
    { done: counters.opportunities > 0, label: "Add a job opportunity and run AI matching", to: "/opportunities", testId: "step-opportunities" },
    { done: data.gmail_connected, label: "Connect your Gmail account for sending", to: "/gmail", testId: "step-gmail" },
  ];

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle={`Welcome back${data.autopilot?.enabled ? " - Auto-Pilot is watching your queue" : ""}`}
      />

      {isEmpty ? (
        <EmptyState
          icon={Mail}
          title="Your job search starts here"
          description="ApplyPilot is completely user-driven: create role profiles, upload resumes, import HR contacts and let AI match and write every application. No sample data is included."
          testId="dashboard-empty-state"
          actions={steps.map((s) => (
            <Button key={s.to} asChild variant={s.done ? "secondary" : "default"} data-testid={s.testId}>
              <Link to={s.to}>
                {s.done ? <CheckCircle2 className="mr-2 h-4 w-4 text-emerald-500" /> : null}
                {s.label}
              </Link>
            </Button>
          ))}
        />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7 mb-8">
            <StatCard label="Total applications" value={stats.total_applications} icon={FileText} testId="stat-total" />
            <StatCard label="Emails sent" value={stats.emails_sent} icon={Mail} testId="stat-sent" />
            <StatCard label="Pending" value={stats.pending} icon={Briefcase} testId="stat-pending" />
            <StatCard label="HR replies" value={stats.hr_replies} icon={CheckCircle2} testId="stat-replies" />
            <StatCard label="Interviews" value={stats.interviews} icon={TrendingUp} testId="stat-interviews" />
            <StatCard label="Failed" value={stats.failed} icon={Briefcase} testId="stat-failed" />
            <StatCard label="Success rate" value={`${stats.success_rate}%`} icon={BarChart3} testId="stat-success" sub="replies / sent" />
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3 mb-8">
            <Card className="lg:col-span-2">
              <CardHeader><CardTitle className="text-base">Applications & emails sent (last 14 days)</CardTitle></CardHeader>
              <CardContent className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data.per_day} data-testid="chart-per-day">
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d) => d.slice(5)} />
                    <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                    <RTooltip />
                    <Bar dataKey="applications" name="Applications" fill="#0D9488" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="sent" name="Sent" fill="#3B82F6" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="text-base">Status distribution</CardTitle></CardHeader>
              <CardContent className="h-72">
                {data.status_distribution.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No data yet</p>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={data.status_distribution.map((s) => ({ ...s, name: STATUS_META[s.status]?.label || s.status }))}
                        dataKey="count" nameKey="name" innerRadius={55} outerRadius={90} paddingAngle={3}
                      >
                        {data.status_distribution.map((s, i) => (
                          <Cell key={s.status} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <RTooltip />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <Card>
              <CardHeader><CardTitle className="text-base">Recent activity</CardTitle></CardHeader>
              <CardContent>
                {data.recent_activity.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No activity yet</p>
                ) : (
                  <ul className="space-y-4" data-testid="recent-activity-list">
                    {data.recent_activity.map((e) => {
                      const Icon = EVENT_ICONS[e.type] || FileText;
                      return (
                        <li key={e.id} className="flex items-start gap-3">
                          <div className="rounded-full bg-muted p-2"><Icon className="h-3.5 w-3.5" /></div>
                          <div className="min-w-0">
                            <p className="text-sm font-medium">{e.detail}</p>
                            <p className="text-xs text-muted-foreground">{new Date(e.created_at).toLocaleString()}</p>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="text-base">Today & counters</CardTitle>
                <StatusBadge status={data.autopilot?.paused ? "cancelled" : data.autopilot?.enabled ? "sent" : "draft"} className="hidden" />
              </CardHeader>
              <CardContent className="space-y-3" data-testid="dashboard-counters">
                <div className="flex justify-between text-sm"><span className="text-muted-foreground">Sent today</span><span className="font-semibold">{counters.sent_today} / {counters.daily_limit}</span></div>
                <div className="flex justify-between text-sm"><span className="text-muted-foreground">Role profiles</span><span className="font-semibold">{counters.role_profiles}</span></div>
                <div className="flex justify-between text-sm"><span className="text-muted-foreground">HR contacts</span><span className="font-semibold">{counters.hr_contacts}</span></div>
                <div className="flex justify-between text-sm"><span className="text-muted-foreground">Job opportunities</span><span className="font-semibold">{counters.opportunities}</span></div>
                <div className="flex justify-between text-sm"><span className="text-muted-foreground">Follow-ups awaiting review</span><span className="font-semibold">{counters.followups_pending}</span></div>
                <div className="flex justify-between text-sm"><span className="text-muted-foreground">Gmail</span><span className="font-semibold">{data.gmail_connected ? "Connected" : "Not connected"}</span></div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2 text-base"><CalendarClock className="h-4 w-4 text-primary" /> Upcoming interviews</CardTitle></CardHeader>
              <CardContent data-testid="upcoming-interviews">
                {!data.upcoming_interviews?.length ? (
                  <p className="text-sm text-muted-foreground">No interviews scheduled. When an HR replies and you mark a row as "interview" in the Tracker, schedule it here.</p>
                ) : (
                  <ul className="space-y-4">
                    {data.upcoming_interviews.map((iv, i) => (
                      <li key={i} className="rounded-lg border p-3">
                        <p className="text-sm font-medium">{iv.company} — {iv.job_title}</p>
                        <p className="text-xs text-primary font-semibold mt-1">{new Date(iv.interview_at).toLocaleString()}</p>
                        {iv.interview_notes && <p className="mt-1 text-xs text-muted-foreground">{iv.interview_notes}</p>}
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
