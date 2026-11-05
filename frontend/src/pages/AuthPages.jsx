import { Mail } from "lucide-react";
import { SignIn, SignUp } from "@clerk/react";
import { Brand } from "@/components/layout/AppShell";

function AuthLayout({ children, title, subtitle }) {
  return (
    <div className="flex min-h-screen">
      <div className="hidden lg:flex lg:w-1/2 flex-col justify-between bg-[#090D16] p-12 text-slate-100">
        <Brand />
        <div className="max-w-md">
          <h1 className="font-display text-4xl font-extrabold tracking-tight leading-tight">
            Your AI agent for job applications.
          </h1>
          <p className="mt-4 text-slate-400">
            Create role profiles, upload tailored resumes, connect Gmail, and let ApplyPilot match,
            personalize and send every application for you.
          </p>
        </div>
        <p className="text-xs text-slate-600">Personalized outreach, real Gmail delivery, full control.</p>
      </div>
      <div className="flex flex-1 flex-col items-center justify-center gap-6 p-6">
        <div className="lg:hidden">
          <Brand />
        </div>
        <div className="text-center">
          <h2 className="font-display text-2xl font-bold">{title}</h2>
          <p className="text-sm text-muted-foreground mt-1">{subtitle}</p>
        </div>
        {children}
      </div>
    </div>
  );
}

export function SignInPage() {
  return (
    <AuthLayout title="Welcome back" subtitle="Sign in to your ApplyPilot workspace">
      <SignIn routing="path" path="/sign-in" signUpUrl="/sign-up" withSignUp />
    </AuthLayout>
  );
}

export function SignUpPage() {
  return (
    <AuthLayout title="Create your account" subtitle="Start running your job search on autopilot">
      <SignUp routing="path" path="/sign-up" signInUrl="/sign-in" />
    </AuthLayout>
  );
}

export default SignInPage;
