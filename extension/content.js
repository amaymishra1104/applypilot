// ApplyPilot browser helper - injected into job pages: read job details, fill and submit forms.
(() => {
  if (window.__applypilot) return;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const q = (sels) => { for (const s of sels) { const el = document.querySelector(s); if (el && clean(el.innerText)) return clean(el.innerText); } return ""; };
  const visible = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el); return r.width > 0 && r.height > 0 && st.visibility !== "hidden" && st.display !== "none"; };
  const host = location.hostname;
  const board = ["linkedin", "naukri", "indeed", "internshala", "wellfound", "instahyre"].find((b) => host.includes(b)) || "other";

  function jsonLdJob() {
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const items = [].concat(JSON.parse(s.textContent));
        const all = items.flatMap((i) => (i["@graph"] ? i["@graph"] : [i]));
        const job = all.find((i) => i["@type"] === "JobPosting");
        if (job) {
          const d = document.createElement("div");
          d.innerHTML = job.description || "";
          const loc = [].concat(job.jobLocation || [])[0];
          return { title: job.title, company: job.hiringOrganization?.name || "", description: clean(d.innerText),
            location: loc?.address?.addressLocality || "" };
        }
      } catch (e) { /* ignore bad json */ }
    }
    return null;
  }

  const SELECTORS = {
    title: [".job-details-jobs-unified-top-card__job-title", ".top-card-layout__title", "[data-testid='jobsearch-JobInfoHeader-title']",
      ".jobsearch-JobInfoHeader-title", ".profile_on_detail_page", ".heading_4_5.profile", "h1"],
    company: [".job-details-jobs-unified-top-card__company-name", ".topcard__org-name-link", "[data-testid='inlineHeader-companyName']",
      "[class*='jd-header-comp-name']", ".company_name a", ".company-name", "[class*='company-name']"],
    description: ["#job-details", ".jobs-description__content", ".show-more-less-html__markup", "#jobDescriptionText",
      "[class*='job-desc']", ".internship_details", "[class*='description']", "main"],
  };

  function jobUrl() {
    const id = new URLSearchParams(location.search).get("currentJobId");
    if (board === "linkedin" && id) return `https://www.linkedin.com/jobs/view/${id}/`;
    const jk = new URLSearchParams(location.search).get("vjk") || new URLSearchParams(location.search).get("jk");
    if (board === "indeed" && jk) return `${location.origin}/viewjob?jk=${jk}`;
    return location.href;
  }

  function extract() {
    const ld = jsonLdJob() || {};
    const og = document.querySelector('meta[property="og:title"]')?.content || document.title;
    return {
      url: jobUrl(), board,
      title: clean(ld.title) || q(SELECTORS.title) || clean(og),
      company: clean(ld.company) || q(SELECTORS.company),
      location: clean(ld.location),
      description: (ld.description || q(SELECTORS.description)).slice(0, 18000),
    };
  }

  // ---------------------------------------------------------------- form filling
  function labelOf(el) {
    const parts = [el.getAttribute("aria-label"), el.placeholder, el.name, el.id];
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) parts.unshift(l.innerText); }
    const wrap = el.closest("label, fieldset, .form-group, [class*='form-element'], [class*='question'], div");
    if (wrap) parts.push(wrap.querySelector("legend, label, span, p")?.innerText);
    return clean(parts.filter(Boolean).join(" ")).toLowerCase().slice(0, 300);
  }

  function valueFor(label, p, app) {
    const custom = (p.custom_answers || []).find((a) => a.question && label.includes(a.question.toLowerCase()));
    if (custom) return custom.answer;
    const [first, ...rest] = (p.full_name || "").split(" ");
    const rules = [
      [/first.?name|given name/, first], [/last.?name|surname|family name/, rest.join(" ")],
      [/full.?name|^name|your name|candidate name/, p.full_name], [/e-?mail/, p.email],
      [/phone|mobile|contact number|whatsapp/, p.phone], [/linkedin/, p.linkedin_url], [/github/, p.github_url],
      [/portfolio|website|personal site|blog/, p.portfolio_url], [/notice/, p.notice_period],
      [/current.*(ctc|salary|compensation)/, p.current_ctc], [/expect.*(ctc|salary|compensation)|salary expectation|desired salary/, p.expected_ctc],
      [/years.*experience|experience.*years|total experience|how many years/, p.years_experience],
      [/current.*(company|employer|organi[sz]ation)/, p.current_company], [/current.*(title|designation|role|position)/, p.current_title],
      [/authori[sz]|visa|sponsor|legally/, p.work_authorization], [/relocat/, p.willing_to_relocate],
      [/city|location|where are you based/, p.city],
      [/cover letter|why should (we|you)|why do you want|about yourself|additional information|message to|hire you/, app?.body_text],
    ];
    const hit = rules.find(([rx]) => rx.test(label));
    return hit ? hit[1] || "" : "";
  }

  function setValue(el, value) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function attachResume(input, resume) {
    if (!resume || (input.files && input.files.length)) return false;
    const bytes = Uint8Array.from(atob(resume.b64), (c) => c.charCodeAt(0));
    const dt = new DataTransfer();
    dt.items.add(new File([bytes], resume.name || "resume.pdf", { type: "application/pdf" }));
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    input.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  }

  function fillAll(ctx) {
    const p = ctx.profile || {};
    let filled = 0;
    const missing = [];
    const root = document.querySelector("[role='dialog'] form, [role='dialog'], .jobs-easy-apply-modal") || document;
    for (const el of root.querySelectorAll("input, textarea, select")) {
      if (!visible(el) && el.type !== "file") continue;
      const type = (el.type || "").toLowerCase();
      if (["hidden", "submit", "button", "search", "password", "checkbox"].includes(type)) continue;
      const label = labelOf(el);
      if (type === "file") {
        if (/resume|cv|upload/.test(label) || /pdf/.test(el.accept || "") || !el.accept) {
          if (attachResume(el, ctx.resume)) filled++;
        }
        continue;
      }
      if (type === "radio") {
        const v = valueFor(labelOf(el.closest("fieldset") || el.parentElement), p, ctx.app).toLowerCase();
        const own = clean((el.labels && el.labels[0]?.innerText) || el.value).toLowerCase();
        if (v && own && (own === v || v.startsWith(own)) && !el.checked) { el.click(); filled++; }
        continue;
      }
      const value = valueFor(label, p, ctx.app);
      if (el.tagName === "SELECT") {
        if (el.selectedIndex > 0 || !value) { if (el.required && el.selectedIndex <= 0) missing.push(label); continue; }
        const opt = [...el.options].find((o) => clean(o.text).toLowerCase().includes(value.toLowerCase()));
        if (opt) { el.value = opt.value; el.dispatchEvent(new Event("change", { bubbles: true })); filled++; }
        else if (el.required) missing.push(label);
        continue;
      }
      if (clean(el.value)) continue;
      if (value) { setValue(el, String(value)); filled++; }
      else if (el.required || el.getAttribute("aria-required") === "true") missing.push(label);
    }
    return { filled, missing: [...new Set(missing)].slice(0, 5) };
  }

  // ---------------------------------------------------------------- buttons & flow
  const SUCCESS = /application (was |has been )?(sent|submitted)|applied successfully|successfully applied|you have applied|thank you for applying|your application (is|was) (on its way|received)/i;
  function buttons() {
    return [...document.querySelectorAll("button, input[type=submit], a[role=button], [role=button]")]
      .filter((b) => visible(b) && !b.disabled && b.getAttribute("aria-disabled") !== "true");
  }
  const textOf = (b) => clean(b.innerText || b.value || b.getAttribute("aria-label")).toLowerCase();
  const find = (rx) => buttons().find((b) => rx.test(textOf(b)));

  function startButton() {
    if (board === "linkedin") return buttons().find((b) => /easy apply/.test(textOf(b)));
    return find(/^(easy apply|apply now|apply on company site|apply|i'?m interested|interested|quick apply)$/);
  }

  async function run(ctx) {
    if (SUCCESS.test(document.body.innerText)) return { outcome: "submitted", detail: "Already applied" };
    const hasForm = () => document.querySelector("[role='dialog'] input, [role='dialog'] textarea, form input[type=file], form textarea");
    if (!hasForm()) {
      if (board === "linkedin" && !startButton() && find(/^apply/)) {
        return { outcome: "needs_attention", detail: "This LinkedIn job applies on the company website - finish it there" };
      }
      const start = startButton();
      if (start) { start.click(); await sleep(2500); }
      if (SUCCESS.test(document.body.innerText)) return { outcome: "submitted", detail: "Applied in one click" };
    }
    for (let step = 0; step < 12; step++) {
      const { missing } = fillAll(ctx);
      await sleep(600);
      if (missing.length) {
        return { outcome: "needs_attention", detail: `Needs your answer for: ${missing.join("; ")}` };
      }
      const submit = find(/^(submit application|submit|send application|apply|finish|done)$/);
      const next = find(/^(next|continue|review|review your application|proceed|save and continue)/);
      if (ctx.mode === "fill") {
        return { outcome: "filled", detail: submit ? "Form filled - review it and click Submit yourself" : "Filled this step - click Next/Continue yourself, then Autofill again" };
      }
      const btn = submit || next;
      if (!btn) {
        if (!hasForm() && step > 0) return { outcome: "continue" };
        return { outcome: "needs_attention", detail: "Could not find the next or submit button" };
      }
      const wasSubmit = btn === submit;
      btn.click();
      await sleep(3000);
      if (SUCCESS.test(document.body.innerText)) return { outcome: "submitted", detail: "Submitted" };
      if (wasSubmit && !hasForm()) return { outcome: "submitted", detail: "Submitted (form closed after submit)" };
    }
    return { outcome: "needs_attention", detail: "The form did not finish after many steps" };
  }

  window.__applypilot = { extract, run };
})();
