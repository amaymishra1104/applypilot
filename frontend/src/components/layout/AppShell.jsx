import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Show, UserButton } from "@clerk/react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useTheme } from "next-themes";
import { toast } from "sonner";
import {
  BarChart3, Briefcase, CalendarClock, FileText, Gauge, LayoutDashboard, Mail,
  Globe, Menu, Moon, Settings as SettingsIcon, Square, Sun, Users,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import Dashboard from "@/pages/Dashboard";
import RoleProfiles from "@/pages/RoleProfiles";
import HRContacts from "@/pages/HRContacts";
import Opportunities from "@/pages/Opportunities";
import EmailGenerator from "@/pages/EmailGenerator";
import ApplicationQueue from "@/pages/ApplicationQueue";
import Tracker from "@/pages/Tracker";
import GmailPage from "@/pages/GmailPage";
import Settings from "@/pages/Settings";
import JobBoards from "@/pages/JobBoards";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/resumes", label: "Resume & Role Profiles", icon: FileText, testId: "nav-resumes" },
  { to: "/contacts", label: "HR Contacts", icon: Users, testId: "nav-contacts" },
  { to: "/opportunities", label: "Job Opportunities", icon: Briefcase, testId: "nav-opportunities" },
  { to: "/boards", label: "Job Boards Auto-Apply", icon: Globe, testId: "nav-boards" },
  { to: "/generator", label: "AI Email Generator", icon: Mail, testId: "nav-generator" },
  { to: "/queue", label: "Application Queue", icon: Gauge, testId: "nav-queue" },
  { to: "/tracker", label: "Application Tracker", icon: CalendarClock, testId: "nav-tracker" },
  { to: "/gmail", label: "Gmail Integration", icon: BarChart3, testId: "nav-gmail" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, testId: "nav-settings" },
];

function Brand({ compact = false }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
        <Mail className="h-5 w-5" />
      </div>
      {!compact && <span className="font-display text-xl font-bold tracking-tight">ApplyPilot</span>}
    </div>
  );
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return (
    <Button
      variant="ghost"
      size="icon"
      data-testid="theme-toggle"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      aria-label="Toggle theme"
    >
      {mounted && theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}

function NavItems({ onNavigate }) {
  return (
    <nav className="flex flex-col gap-1 px-3">
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          data-testid={item.testId}
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
              isActive
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            }`
          }
        >
          <item.icon className="h-4.5 w-4.5 h-[18px] w-[18px]" />
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

function AutopilotPill({ status }) {
  if (!status || !status.autopilot) return null;
  const a = status.autopilot;
  if (!a.enabled) {
    return (
      <Badge variant="outline" className="mx-3 border-slate-500/30 text-slate-500" data-testid="autopilot-pill">
        Auto-Pilot off
      </Badge>
    );
  }
  if (a.paused) {
    return (
      <Badge variant="outline" className="mx-3 bg-red-500/15 text-red-600 dark:text-red-300 border-red-500/40" data-testid="autopilot-pill">
        Auto-Pilot stopped
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="mx-3 whitespace-nowrap bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border-emerald-500/40" data-testid="autopilot-pill">
      Auto-Pilot {a.mode === "auto" ? "on" : a.mode}
    </Badge>
  );
}

export function EmergencyStopButton({ onChanged, testId = "emergency-stop-button" }) {
  const [busy, setBusy] = useState(false);
  const stop = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.post("/autopilot/emergency-stop");
      toast.error("Emergency stop activated - all automatic sending halted");
      onChanged && (await onChanged());
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not trigger emergency stop");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button
      variant="outline"
      size="sm"
      data-testid={testId}
      disabled={busy}
      onClick={stop}
      className="border-red-500/40 text-red-600 dark:text-red-300 hover:bg-red-500/10 hover:text-red-600"
    >
      <Square className="mr-1.5 h-3.5 w-3.5" /> Emergency stop
    </Button>
  );
}

function ShellContent() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [queueStatus, setQueueStatus] = useState(null);

  const refreshStatus = async () => {
    try {
      const res = await api.get("/applications/queue-stats");
      setQueueStatus(res.data);
    } catch {}
  };
  useEffect(() => {
    refreshStatus();
  }, [location.pathname]);

  const current = NAV.find((n) => (n.to === "/" ? location.pathname === "/" : location.pathname.startsWith(n.to)));
  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r bg-card/60 backdrop-blur-xl lg:flex">
        <div className="flex h-16 items-center px-5">
          <Brand />
        </div>
        <NavItems />
        <div className="mt-auto flex flex-col items-start gap-2 px-5 py-4">
          <AutopilotPill status={queueStatus} />
          <EmergencyStopButton testId="emergency-stop-button-sidebar" onChanged={refreshStatus} />
        </div>
      </aside>

      {/* Mobile sidebar */}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-72 p-0">
          <div className="flex h-16 items-center px-5">
            <Brand />
          </div>
          <NavItems onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur-xl sm:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" data-testid="menu-button" onClick={() => setOpen(true)}>
              <Menu className="h-5 w-5" />
            </Button>          <h2 className="min-w-0 truncate font-display text-lg font-semibold" data-testid="page-title">
            {current ? current.label : "Dashboard"}
          </h2>
          <div className="ml-auto flex items-center gap-2">
            <AutopilotPill status={queueStatus} />
            <ThemeToggle />
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div>
                    <UserButton afterSignOutUrl="/" />
                  </div>
                </TooltipTrigger>
                <TooltipContent>Account</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </header>
        <main className="flex-1 p-4 sm:p-6 lg:p-8">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/resumes" element={<RoleProfiles />} />
            <Route path="/contacts" element={<HRContacts />} />
            <Route path="/opportunities" element={<Opportunities />} />
            <Route path="/boards" element={<JobBoards />} />
            <Route path="/generator" element={<EmailGenerator />} />
            <Route path="/queue" element={<ApplicationQueue onChanged={refreshStatus} />} />
            <Route path="/tracker" element={<Tracker />} />
            <Route path="/gmail" element={<GmailPage />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default function AppShell() {
  return (
    <>
      <Show when="signed-in">
        <ShellContent />
      </Show>
      <Show when="signed-out">
        <Navigate to="/sign-in" replace />
      </Show>
    </>
  );
}

export { Brand };
