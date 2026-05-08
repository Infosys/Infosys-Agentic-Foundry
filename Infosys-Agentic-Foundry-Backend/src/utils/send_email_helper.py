import os
import threading
from dotenv import load_dotenv
from telemetry_wrapper import logger
load_dotenv()

APP_URL = os.getenv("UI_CORS_IP_WITH_PORT", "")

# ── SMTP configuration (loaded from .env) ──────────────────────────
SMTP_SENDER_EMAIL_ADDRESS = os.getenv("SMTP_SENDER_EMAIL_ADDRESS", "")
SMTP_IP = os.getenv("SMTP_IP", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "25"))
SMTP_USER = os.getenv("SMTP_USER", "") or None
SMTP_PASS = os.getenv("SMTP_PASS", None)
SMTP_REQUIRES_AUTH = os.getenv("SMTP_REQUIRES_AUTH", "false").lower() == "true"
USE_SSL_CONNECTION = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
USE_TLS_CONNECTION = os.getenv("SMTP_USE_TLS", "false").lower() == "true"
SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "3"))


def send_email(recipient_list: list, subject: str, body: str) -> bool:
    """
    Sends an email to a list of recipients using a custom SMTP server without authentication.

    Args:
        recipient_list (list): A list of email addresses to send the email to.
        subject (str): The subject line of the email.
        body (str): The body content of the email.

    Returns:
        bool: True if the email was sent successfully to all recipients, False otherwise.
    """

    try:
        raise NotImplementedError("Email sending is currently disabled.")

    except Exception as e:
        logger.error(f'Failed to send email. An unexpected error occurred: {e}')
        return False


def _send_email_async(recipient_list: list, subject: str, body: str):
    """Fire-and-forget email sending in a background thread."""
    t = threading.Thread(target=send_email, args=(recipient_list, subject, body), daemon=True)
    t.start()


def notify_admins_new_registration(admin_emails: list, user_email: str, user_name: str, departments: list):
    """Notify admins when a new user registers and requests department access."""
    if not admin_emails:
        return
    dept_list = ", ".join(departments)
    app_line = f"  Application: {APP_URL}\n" if APP_URL else ""
    _send_email_async(
        recipient_list=admin_emails,
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
    dept_list = ", ".join(departments)
    app_line = f"  Application: {APP_URL}\n" if APP_URL else ""
    _send_email_async(
        recipient_list=admin_emails,
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
        recipient_list=[user_email],
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
        recipient_list=[user_email],
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
