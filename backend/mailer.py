"""Notification mailer delivering account owner notifications (replies, reminders, digests)
via:
  1) Connected Gmail account (if owner has connected Gmail),
  2) SMTP (if SMTP_HOST is configured),
  3) Log-only fallback with a visible warning.

All external application emails to HR contacts are sent exclusively via connected Gmail.
"""

import asyncio
from html import escape
from html.parser import HTMLParser
import ipaddress
import logging
import os
import re
import smtplib
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlparse

from dotenv import load_dotenv

from db import db

load_dotenv()
logger = logging.getLogger(__name__)

EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "ApplyPilot")
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO")

_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = (
    "reply with your password", "reply with the code", "send your password", "cvv",
    "send us your password", "enter your password below", "confirm your card number",
    "your full card number", "seed phrase", "recovery phrase", "verify your card",
    "social security number", "confirm your bank details"
)
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} ≠ real link host {real!r} (G3)")


def html_to_plain_text(html: str) -> str:
    text = re.sub(r"<style.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</tr>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</td>", "  ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _send_smtp_sync(to: str, subject: str, html: str, text: str, reply_to: str | None = None) -> str:
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    from_addr = os.environ.get("SMTP_FROM") or os.environ.get("EMAIL_FROM") or (f"{EMAIL_FROM_NAME} <{user}>" if user else "notifications@applypilot.local")

    msg = MIMEMultipart("alternative")
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to or EMAIL_REPLY_TO:
        msg["Reply-To"] = reply_to or EMAIL_REPLY_TO

    msg.attach(MIMEText(text or "", "plain"))
    if html:
        msg.attach(MIMEText(html, "html"))

    use_ssl = port == 465 or os.environ.get("SMTP_USE_SSL", "false").lower() in ("true", "1")
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() in ("true", "1")

    if use_ssl:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        if use_tls:
            server.starttls()

    if user and password:
        server.login(user, password)

    server.send_message(msg)
    server.quit()
    return f"smtp_{uuid.uuid4().hex[:12]}"


async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    user_id: str | None = None,
    reply_to: str | None = None,
) -> str | None:
    """Send notification email via: 1) connected Gmail, 2) SMTP, 3) log-only fallback."""
    _assert_safe_email(subject, html)
    plain_text = html_to_plain_text(html)
    uid = user_id or "owner"

    # Channel 1: Connected Gmail account
    try:
        conn = await db.gmail_connections.find_one({"user_id": uid})
        if conn and conn.get("status") == "connected":
            import gmail_service
            msg_id, _ = await gmail_service.send_gmail_email(
                user_id=uid,
                to=to,
                subject=subject,
                body_text=plain_text,
                html_body=html,
                reply_to=reply_to or EMAIL_REPLY_TO,
            )
            if msg_id:
                logger.info("Delivered notification via connected Gmail to %s (message %s)", to, msg_id)
                return f"gmail_{msg_id}"
    except Exception as exc:
        logger.warning("Failed to send notification via Gmail for user %s: %s. Trying SMTP fallback.", uid, exc)

    # Channel 2: SMTP server
    smtp_host = os.environ.get("SMTP_HOST")
    if smtp_host:
        try:
            message_id = await asyncio.to_thread(
                _send_smtp_sync,
                to=to,
                subject=subject,
                html=html,
                text=plain_text,
                reply_to=reply_to,
            )
            logger.info("Delivered notification via SMTP to %s", to)
            return message_id
        except Exception as exc:
            logger.warning("Failed to send notification via SMTP to %s: %s. Falling back to log.", to, exc)

    # Channel 3: Log-only fallback with visible warning
    logger.warning(
        "Notification delivery: neither connected Gmail nor SMTP is available or working. "
        "[NOTIFICATION LOG ONLY] To: %s | Subject: %s | Body:\n%s",
        to,
        subject,
        plain_text[:300],
    )
    return f"log_only_{uuid.uuid4().hex[:12]}"


def _wrap(title: str, body_html: str) -> str:
    return (
        f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif">'
        f'<h2 style="margin:0 0 12px;color:#0F172A">{escape(title)}</h2>{body_html}'
        f'<p style="font-size:12px;color:#888;margin-top:24px">Sent by {escape(EMAIL_FROM_NAME)}. '
        f"We never ask for your password or card details by email.</p></td></tr></table>"
    )


async def notify_user(user: dict, kind: str, context: dict) -> str | None:
    """Notification to the account owner's email address."""
    to = (user or {}).get("email", "")
    if not to:
        return None
    uid = (user or {}).get("user_id") or "owner"

    if kind == "application_sent":
        subject = f"Application sent: {context.get('company', '')}"
        html = _wrap(
            "Application sent",
            f"<p>Your application to <strong>{escape(context.get('company', ''))}</strong> "
            f"({escape(context.get('role', ''))}) was sent with resume "
            f"<strong>{escape(context.get('resume', ''))}</strong>.</p>",
        )
    elif kind == "reply_received":
        subject = f"HR reply from {context.get('company', '')}"
        html = _wrap(
            "New HR reply",
            f"<p>{escape(context.get('company', ''))} replied to your application "
            f"for <strong>{escape(context.get('role', ''))}</strong>.</p>"
            f"<p><em>{escape(context.get('summary', ''))}</em></p>",
        )
    elif kind == "followup_ready":
        subject = f"Follow-up ready for review: {context.get('company', '')}"
        html = _wrap(
            "Follow-up ready",
            f"<p>A follow-up draft for <strong>{escape(context.get('company', ''))}</strong> "
            "is ready. Review and approve it in your Application Tracker.</p>",
        )
    elif kind == "autopilot_paused":
        subject = "Auto-Pilot emergency stop triggered"
        html = _wrap("Auto-Pilot stopped", f"<p>{escape(context.get('reason', ''))}</p>")
    elif kind == "interview_reminder":
        subject = f"Interview reminder: {context.get('company', '')}"
        html = _wrap(
            "Interview coming up",
            f"<p>Your interview with <strong>{escape(context.get('company', ''))}</strong> "
            f"is scheduled for <strong>{escape(context.get('when', ''))}</strong>.</p>"
            f"<p>{escape(context.get('notes', ''))}</p>",
        )
    elif kind == "send_failed":
        subject = f"Send failed: {context.get('company', '')}"
        html = _wrap(
            "Send failed",
            f"<p>Sending to {escape(context.get('company', ''))} failed after retries: "
            f"{escape(context.get('error', ''))}</p>",
        )
    elif kind == "board_digest":
        apps = context.get("apps", [])
        subject = f"{len(apps)} new board job{'s' if len(apps) != 1 else ''} waiting for your approval"
        rows = "".join(
            f'<tr><td style="padding:6px 0;border-bottom:1px solid #eee"><strong>{escape(a.get("job_title", ""))}</strong>'
            f' - {escape(a.get("company") or "Company not listed")}<br><span style="color:#555;font-size:13px">'
            f'{escape(a.get("board", ""))} · {int(a.get("match_score", 0))}% match · {escape(a.get("role_profile_title", ""))}</span>'
            + (f' · <a href="{escape(a["job_url"])}">View job</a>' if str(a.get("job_url", "")).startswith("https://") else "")
            + "</td></tr>"
            for a in apps[:15]
        )
        more = f"<p>And {len(apps) - 15} more.</p>" if len(apps) > 15 else ""
        html = _wrap(
            "Your morning job board digest",
            f'<table role="presentation" width="100%">{rows}</table>{more}'
            "<p>Open <strong>Job Boards Auto-Apply</strong> in ApplyPilot to approve the ones you want - "
            "the browser helper submits them after approval.</p>",
        )
    else:
        return None

    return await send_email(to=to, subject=subject, html=html, user_id=uid)
