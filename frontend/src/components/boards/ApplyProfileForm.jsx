import { useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const FIELDS = [
  ["full_name", "Full name"], ["email", "Email"], ["phone", "Phone"], ["city", "Current city"],
  ["linkedin_url", "LinkedIn URL"], ["github_url", "GitHub URL"], ["portfolio_url", "Portfolio / website"],
  ["current_title", "Current job title"], ["current_company", "Current company"],
  ["years_experience", "Total experience (years)"], ["notice_period", "Notice period"],
  ["current_ctc", "Current salary / CTC"], ["expected_ctc", "Expected salary / CTC"],
  ["work_authorization", "Work authorization (e.g. Yes, authorized in India)"],
  ["willing_to_relocate", "Willing to relocate (Yes / No)"],
];

function AnswerRow({ item, onChange, onRemove, index }) {
  return (
    <div className="grid gap-2 rounded-lg border p-3 md:grid-cols-[1fr_2fr_auto]">
      <Input placeholder="Question keyword, e.g. Why should we hire you" value={item.question}
        onChange={(e) => onChange({ ...item, question: e.target.value })} data-testid={`answer-question-${index}`} />
      <Textarea rows={2} placeholder="Your answer" value={item.answer}
        onChange={(e) => onChange({ ...item, answer: e.target.value })} data-testid={`answer-text-${index}`} />
      <Button variant="ghost" size="icon" onClick={onRemove} data-testid={`answer-remove-${index}`}><Trash2 className="h-4 w-4" /></Button>
    </div>
  );
}

export function ApplyProfileForm({ profile, onChanged }) {
  const [form, setForm] = useState({ custom_answers: [], ...profile });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const answers = form.custom_answers || [];
  const save = async () => {
    setBusy(true);
    try {
      await api.put("/boards/apply-profile", form);
      toast.success("Application answers saved");
      onChanged();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not save");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Answers the helper uses to fill application forms</CardTitle>
        <p className="text-sm text-muted-foreground">Only what you enter here is used. Empty fields are left for you to fill.</p>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {FIELDS.map(([k, label]) => (
            <div key={k} className="space-y-1.5">
              <Label htmlFor={`ap-${k}`}>{label}</Label>
              <Input id={`ap-${k}`} value={form[k] || ""} onChange={(e) => set(k, e.target.value)} data-testid={`apply-profile-${k}`} />
            </div>
          ))}
        </div>
        <div className="space-y-3">
          <Label>Custom screening answers</Label>
          {answers.map((a, i) => (
            <AnswerRow key={i} index={i} item={a}
              onChange={(v) => set("custom_answers", answers.map((x, j) => (j === i ? v : x)))}
              onRemove={() => set("custom_answers", answers.filter((_, j) => j !== i))} />
          ))}
          <Button variant="outline" size="sm" onClick={() => set("custom_answers", [...answers, { question: "", answer: "" }])} data-testid="add-custom-answer">
            <Plus className="mr-1.5 h-4 w-4" /> Add answer
          </Button>
        </div>
        <Button onClick={save} disabled={busy} data-testid="save-apply-profile">Save answers</Button>
      </CardContent>
    </Card>
  );
}
