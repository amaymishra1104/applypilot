# ApplyPilot — PRD

## Original problem statement
Build ApplyPilot, an AI-powered personal job application agent: users create custom role profiles, upload versioned PDF resumes per role, import HR contacts (CSV/Excel), add/paste/scan job opportunities, let AI match each job to the best role profile + active resume, generate personalized emails, and send real applications through their own Gmail (OAuth 2.0) with the exact resume version attached. Includes dashboard analytics, application tracker with HR reply detection & classification, smart follow-ups, auto-pilot (daily limits, duplicate prevention, emergency stop), and settings. Entirely dynamic — never any sample roles/resumes/companies. User follow-up: upgrade with advanced AI (Gmail inbox opportunity scanning, company research, ATS analysis, reply classification), keep everything real (no simulated statuses), no UI redesign.

## User choices (ask_human)
- Auth: email + password (delivered via Emergent-managed Clerk)
- AI: Emergent Universal LLM key (default model gpt-5.4, configurable)
- Email: Gmail OAuth 2.0 (user's own Google Cloud credentials) + Emergent managed email used for owner notifications only (platform policy: application emails to uploaded HR lists must go through the user's own Gmail, not the shared managed sender)
- Storage: Emergent Object Storage for private PDF resumes

## Architecture
- Frontend: React (CRA) + Tailwind + shadcn/ui, Clerk auth, next-themes (dark default + light), recharts. Pages: Dashboard, Resume & Role Profiles, HR Contacts, Job Opportunities, AI Email Generator, Application Queue, Application Tracker, Gmail Integration, Settings, sign-in/sign-up.
- Backend: FastAPI (backend/server.py + routers), Motor/MongoDB, emergentintegrations LlmChat, google-auth-oauthlib + googleapiclient, pypdf text extraction, openpyxl Excel import, Fernet-encrypted OAuth tokens & Google client secrets.
- Background work: platform crons (.emergent/crons.yml): autopilot-tick (*/15), reply-scan (*/30), followup-reminders (daily 13:00 UTC) → POST /api/cron/* with WEBHOOK_CRON_SECRET bearer auth, idempotent via cron_runs, ack 2xx + background task.
- Storage: applypilot/resumes/{user_id}/{uuid}.pdf in Emergent Object Storage; DB is source of truth.

## Data model (MongoDB collections, all scoped by user_id)
users, role_profiles, resume_versions (versioned, one active per role, resume_text extracted), hr_contacts (dup detection via hr_email_norm), companies (AI research), job_opportunities, job_matches (score, confidence, reasoning, matched/missing skills, ATS report, confirm/override), job_applications (snapshot of role_profile_title + resume_version_no + attachment_path → historical accuracy preserved even after edits/deletes), application_events (activity feed), follow_ups (AI drafts, approval required), gmail_connections (encrypted tokens), google_oauth_config (encrypted client id/secret per user), oauth_states (TTL), app_settings, reply_scan_state, cron_runs.

## Implemented (2026-11-04)
- Clerk email+password auth, per-user data isolation (404 on foreign records, verified)
- Role profiles CRUD + resume upload (PDF ≤5MB validation, text extraction), auto-activate new version, version history, activate/preview/download/delete
- HR contacts manual + CSV/XLSX import with duplicate detection, search, CSV template
- Opportunities: manual entry, paste JD → AI parse, CSV import, Gmail inbox scan for hiring opportunities, AI company research (honesty caveats)
- AI matching: extracts skills/experience, scores all profiles, picks best, reasoning + alternatives + confidence; manual override of role/resume; confirm gate
- ATS resume analysis (score, matched/missing keywords, suggestions)
- Personalized email generation (tone config, no-fabrication prompts), editable subject/body
- Applications: status pipeline (draft → awaiting_approval → approved/queued_auto → sent → replied/interview/rejected/offer, send_failed, cancelled), send via Gmail API with exact resume PDF attached, duplicate check (hr_email+job_title), invalid-email + disposable-domain blocking, daily limit enforcement, retry limits
- Auto-pilot: manual/approval/auto modes, max/day, min delay, min match score, run-now, emergency stop (sidebar + queue), cascade-failure auto-pause; crons for autopilot/reply-scan/followups
- Reply detection: Gmail inbox scan → AI classification (interview/interested/rejection/auto_response) → status update, follow-up cancellation, owner notification
- Smart follow-ups: AI drafts after N days no-reply, user approves before send
- Dashboard: 7 real stats, 14-day bar chart, status donut, recent activity, counters; getting-started empty state; zero fake data
- Tracking history table + CSV export; Settings page (model, tone, autopilot, follow-ups, notifications + test email, security)
- Interview Calendar (2026-11-04): schedule interview date/time + notes on interview-stage applications (POST /api/applications/{id}/schedule-interview), reminder cron (interview-reminders, */30) firing an in-app event + owner email within configurable lead hours, Dashboard "Upcoming interviews" card, Tracker Interview column with scheduling dialog, Settings reminder-hours + toggle (persistence bug found by testing agent fixed and re-verified)
- Job Boards Auto-Apply (2026-11-05): user request "apply for the autoapply jobs on linkedin, naukri, indeed, internshala, wellfound, instahyre and other job boards" (picked all options: browser helper, automatic bot, apply-by-email, save-while-browsing + automatic keyword search, auto above score + approval). Built: /boards page (applications, automatic search, browser helper, application answers tabs); Chrome MV3 helper in /app/extension (zip at /applypilot-extension.zip) — saves jobs (JSON-LD + per-board selectors), autofills forms incl. resume PDF upload, auto-submits approved/auto-queued jobs in background tabs using the user's own logged-in browser sessions (no board passwords stored — server-side bots get captcha-blocked and can't run in deployment); connection code = base64{u,t} with hashed, revocable token (X-ApplyPilot-Token); board search adapters (LinkedIn guest API, Internshala, Wellfound, Instahyre, Remotive, Arbeitnow working; Naukri/Indeed report honest 'blocked'); cron board-search every 6h; board applications channel=board with statuses submitting/needs_attention, honoring autopilot mode, min score, daily limit, delay and emergency stop; HR emails in postings become contacts → 'Apply by email instead' (switch-to-email cancels the board app). Tested iteration_3 + iteration_4 (all pass).
- Daily Board Digest (2026-11-05): hourly cron board-digest emails each user (managed email, own verified address) at their chosen local hour (Settings > Daily board digest: on/off, hour 0-23, browser timezone saved) a list of new board applications awaiting approval since the last digest; skipped when none; once per local day; failed sends retry next hour; 'Send digest now' button. Global axios interceptor flattens 422 detail arrays. Tested iteration_5 + iteration_6.
- Gmail Integration page: connect/disconnect, encrypted credential entry, redirect URI display, Google Cloud setup guide

## Verification
- E2E API script: all green (roles, 3 versions with auto-activation, dup 409, AI parse, match 96% correct profile, ATS, email generation, clean 400 without Gmail, cron auth 401/200, isolation 404, CSV export)
- Testing agent (iteration_1): found emergency-stop unpause missing (fixed in AutopilotIn both routers), duplicate-key race on user init (fixed), duplicate testids (fixed); re-verified paused reset + settings GET + queue stats via API
- Screenshots: sign-in (desktop/mobile), dashboard, queue — all rendering correctly, no overflow

## Backlog / next
- P0: none blocking
- P1: Live test of browser helper on real board accounts (needs user's Chrome); per-board flow tuning from real results
- P1: Gmail OAuth live test with owner's Google Cloud credentials (needs user action); interview scheduling calendar; per-opportunity HR contact linking UI polish
- P2: multiple Gmail accounts, email threading on follow-ups (In-Reply-To headers), weekly analytics digest, role profile cloning
