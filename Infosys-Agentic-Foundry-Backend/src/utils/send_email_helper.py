import os
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv
from telemetry_wrapper import logger
load_dotenv()

APP_URL = os.getenv("UI_CORS_IP_WITH_PORT", "")

# Comma-separated list of email addresses that should NOT receive admin notification emails
ADMIN_EMAIL_EXCLUDE_LIST = [
    email.strip().lower()
    for email in os.getenv("ADMIN_EMAIL_EXCLUDE_LIST", "").split(",")
    if email.strip()
]


def _filter_excluded_admin_emails(admin_emails: list) -> list:
    """Remove excluded emails from the admin recipient list."""
    if not ADMIN_EMAIL_EXCLUDE_LIST:
        return admin_emails
    return [e for e in admin_emails if e.lower() not in ADMIN_EMAIL_EXCLUDE_LIST]


def send_email(to_email: list, subject: str, body: str, html: bool = False, cc: list = None, attachments: list = None):
    """
    Send an email with optional CC and file attachments.

    Args:
        to_email (list): Recipient email address(es).
        subject (str): Email subject.
        body (str): Email body content.
        html (bool): If True, send body as HTML. Default is plain text.
        cc (list, optional): CC recipient(s).
        attachments (list, optional): List of file paths to attach.
    """
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", 25))
    sender_email = os.getenv("SMTP_SENDER_EMAIL_ADDRESS", "")
    smtp_timeout = int(os.getenv("SMTP_TIMEOUT", 3))

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = ", ".join(to_email) if isinstance(to_email, list) else to_email
    msg["Subject"] = subject

    if cc:
        msg["Cc"] = ", ".join(cc) if isinstance(cc, list) else cc

    content_type = "html" if html else "plain"
    msg.attach(MIMEText(body, content_type))

    # Attach files
    if attachments:
        for file_path in attachments:
            if not os.path.isfile(file_path):
                logger.warning(f"Attachment not found: {file_path}")
                continue
            with open(file_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(file_path)}")
            msg.attach(part)

    # Build full recipient list (To + CC)
    recipients = to_email if isinstance(to_email, list) else [to_email]
    if cc:
        recipients += cc if isinstance(cc, list) else [cc]

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=smtp_timeout) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.sendmail(sender_email, recipients, msg.as_string())
        logger.info(f"Email sent successfully to {msg['To']}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")


def _send_email_async(to_email: list, subject: str, body: str, html: bool = False, cc: list = None, attachments: list = None):
    """Fire-and-forget email sending in a background thread."""
    t = threading.Thread(target=send_email, args=(to_email, subject, body, html, cc, attachments), daemon=True)
    t.start()


def notify_admins_new_registration(admin_emails: list, user_email: str, user_name: str, departments: list):
    """Notify admins when a new user registers and requests department access."""
    if not admin_emails:
        return
    admin_emails = _filter_excluded_admin_emails(admin_emails)
    if not admin_emails:
        return
    dept_list = ", ".join(departments)
    app_line = f"  Application: {APP_URL}\n" if APP_URL else ""
    _send_email_async(
        to_email=admin_emails,
        subject=f"[IAF] New User Registration - {user_email}",
        body=(
            f"Hello Admin,\n\n"
            f"A new user has registered and is awaiting your approval.\n\n"
            f"  User Name  : {user_name}\n"
            f"  Email      : {user_email}\n"
            f"  Department(s): {dept_list}\n"
            f"{app_line}\n"
            f"Please log in to approve or reject this request.\n\n"
            f"Regards,\nInfosys Agentic Foundry"
        )
    )


def notify_admins_department_access_request(admin_emails: list, user_email: str, user_name: str, departments: list):
    """Notify admins when an existing user requests access to additional departments."""
    if not admin_emails:
        return
    admin_emails = _filter_excluded_admin_emails(admin_emails)
    if not admin_emails:
        return
    dept_list = ", ".join(departments)
    app_line = f"  Application: {APP_URL}\n" if APP_URL else ""
    _send_email_async(
        to_email=admin_emails,
        subject=f"[IAF] Department Access Request - {user_email}",
        body=(
            f"Hello Admin,\n\n"
            f"An existing user has requested access to additional department(s).\n\n"
            f"  User Name  : {user_name}\n"
            f"  Email      : {user_email}\n"
            f"  Department(s): {dept_list}\n"
            f"{app_line}\n"
            f"Please log in to approve or reject this request.\n\n"
            f"Regards,\nInfosys Agentic Foundry"
        )
    )


def notify_user_request_approved(user_email: str, department_name: str, assigned_role: str, approved_by: str):
    """Notify user that their request was approved."""
    if not user_email:
        return
    app_line = f"  Application: {APP_URL}\n" if APP_URL else ""
    _send_email_async(
        to_email=[user_email],
        subject=f"[IAF] Your Access Request Has Been Approved - {department_name}",
        body=(
            f"Hello, {user_email}\n\n"
            f"Your request to access department '{department_name}' has been approved.\n\n"
            f"  Department   : {department_name}\n"
            f"  Assigned Role: {assigned_role}\n"
            f"  Approved By  : {approved_by}\n"
            f"{app_line}\n"
            f"You can now log in and select '{department_name}' to get started.\n\n"
            f"Regards,\nInfosys Agentic Foundry"
        )
    )


def notify_user_request_rejected(user_email: str, department_name: str, rejected_by: str, rejection_reason: str = None):
    """Notify user that their request was rejected."""
    if not user_email:
        return
    reason_text = rejection_reason if rejection_reason else "No reason provided."
    app_line = f"  Application: {APP_URL}\n" if APP_URL else ""
    _send_email_async(
        to_email=[user_email],
        subject=f"[IAF] Your Access Request Has Been Rejected - {department_name}",
        body=(
            f"Hello, {user_email}\n\n"
            f"Your request to access department '{department_name}' has been rejected.\n\n"
            f"  Department : {department_name}\n"
            f"  Rejected By: {rejected_by}\n"
            f"  Reason     : {reason_text}\n"
            f"{app_line}\n"
            f"If you believe this was in error, please contact your administrator.\n\n"
            f"Regards,\nInfosys Agentic Foundry"
        )
    )
