import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Show } from "@clerk/react";
import { Toaster } from "@/components/ui/sonner";
import ClerkAuthProvider from "@/components/auth/ClerkAuthProvider";
import AppShell from "@/components/layout/AppShell";
import { SignInPage, SignUpPage } from "@/pages/AuthPages";

function App() {
  return (
    <div className="App min-h-screen">
      <BrowserRouter>
        <ClerkAuthProvider>
          <Routes>
            <Route path="/sign-in/*" element={<SignInPage />} />
            <Route path="/sign-up/*" element={<SignUpPage />} />
            <Route path="/*" element={<AppShell />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          <Toaster richColors position="bottom-right" />
        </ClerkAuthProvider>
      </BrowserRouter>
    </div>
  );
}

export default App;
