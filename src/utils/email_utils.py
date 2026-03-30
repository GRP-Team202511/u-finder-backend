"""
Email utility module
Handles sending emails for verification codes and notifications
"""
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from datetime import datetime
from pathlib import Path
from html import escape
import aiosmtplib
import aiofiles
import certifi
import ssl

tls_context = ssl.create_default_context(cafile=certifi.where())

from src.config.settings import get_settings
from src.config.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


async def send_verification_email(
    to_email: str,
    verification_code: str,
    name: str,
    email_type: str = "signup"
) -> bool:
    """
    Send verification code email
    
    Args:
        to_email: Recipient email address
        verification_code: Verification code to send
        name: User's name
        email_type: Type of email ('signup' or 'reset')
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = _get_email_subject(email_type)
        message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        message["To"] = to_email
        
        # Create HTML and plain text versions
        text_content = _get_text_content(verification_code, name, email_type)
        html_content = await _get_html_content(verification_code, name, email_type)
        
        # Attach parts
        part1 = MIMEText(text_content, "plain")
        part2 = MIMEText(html_content, "html")
        message.attach(part1)
        message.attach(part2)
        
        # Development mode: Save email to file instead of sending
        if settings.is_development and not settings.smtp_host:
            return await _save_email_to_file(to_email, verification_code, name, email_type, html_content)
        
        # Configure SMTP connection
        # aiosmtplib naming differs from traditional frameworks:
        #   use_tls  = implicit SSL (port 465)  ← maps to SMTP_USE_SSL
        #   start_tls = STARTTLS (port 587)     ← maps to SMTP_USE_TLS
        smtp_kwargs = {
            "hostname": settings.smtp_host,
            "port": settings.smtp_port,
            "use_tls": settings.smtp_use_ssl,
            "start_tls": settings.smtp_use_tls,
        }
        
        # Send email using aiosmtplib
        async with aiosmtplib.SMTP(**smtp_kwargs, tls_context=tls_context) as smtp:
            if settings.smtp_username and settings.smtp_password:
                await smtp.login(settings.smtp_username, settings.smtp_password)
            await smtp.send_message(message)
        
        logger.info(f"Verification email sent successfully to {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send verification email to {to_email}: {str(e)}")
        return False


def _get_email_subject(email_type: str) -> str:
    """Get email subject based on type"""
    if email_type == "signup":
        return "Welcome to U-Finder - Verify Your Email"
    elif email_type == "reset":
        return "U-Finder - Password Reset Code"
    elif email_type == "delete":
        return "U-Finder - Account Deletion Verification"
    else:
        return "U-Finder - Verification Code"


def _get_text_content(verification_code: str, name: str, email_type: str) -> str:
    """Get plain text email content"""
    if email_type == "signup":
        return f"""
Hello {name},

Welcome to U-Finder! Thank you for signing up.

Your verification code is: {verification_code}

This code will expire in 5 minutes. Please enter this code to complete your registration.

If you didn't sign up for U-Finder, please ignore this email.

Best regards,
The U-Finder Team
"""
    elif email_type == "delete":
        return f"""
Hello {name},

We received a request to permanently delete your U-Finder account.

Your verification code is: {verification_code}

This code will expire in 5 minutes. Please enter this code to confirm account deletion.

Warning: This action is irreversible. Once confirmed, your account and all associated data will be permanently deleted.

If you did not request account deletion, please ignore this email and your account will remain safe.

Best regards,
The U-Finder Team
"""
    else:  # reset
        return f"""
Hello {name},

We received a request to reset your password for your U-Finder account.

Your password reset code is: {verification_code}

This code will expire in 5 minutes. Please enter this code to reset your password.

If you didn't request a password reset, please ignore this email or contact support if you have concerns.

Best regards,
The U-Finder Team
"""


async def _get_html_content(verification_code: str, name: str, email_type: str) -> str:
    """Get HTML email content from file templates with fallback."""
    template_file_map = {
        "signup": "verification-email.html",
        "reset": "resetpassword-email.html",
        "delete": "delete-account-email.html",
    }
    template_name = template_file_map.get(email_type)
    if template_name:
        html_content = await _render_email_template(
            template_name,
            {
                "name": name,
                "verification_code": verification_code,
            },
        )
        if html_content is not None:
            return html_content

    # Keep inline HTML as fallback for unsupported types or missing template files.
    return _get_fallback_html_content(verification_code, name, email_type)


def _get_fallback_html_content(verification_code: str, name: str, email_type: str) -> str:
    """Fallback HTML when template files are unavailable."""
    if email_type == "signup":
        title = "Welcome to U-Finder!"
        message = "Thank you for signing up. Please use the verification code below to complete your registration."
        expiry = "This code will expire in 5 minutes."
    elif email_type == "delete":
        title = "Delete Your Account"
        message = "We received a request to permanently delete your U-Finder account. Please use the verification code below to confirm this action."
        expiry = "This code will expire in 5 minutes. Warning: this action is irreversible."
    else:  # reset
        title = "Password Reset Request"
        message = "We received a request to reset your password. Please use the code below to proceed."
        expiry = "This code will expire in 5 minutes."
    
    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .container {{
            background-color: #f9f9f9;
            border-radius: 10px;
            padding: 30px;
            margin: 20px 0;
        }}
        .header {{
            text-align: center;
            color: #2c3e50;
            margin-bottom: 30px;
        }}
        .code-box {{
            background-color: #fff;
            border: 2px solid #3498db;
            border-radius: 5px;
            padding: 20px;
            text-align: center;
            margin: 30px 0;
        }}
        .code {{
            font-size: 32px;
            font-weight: bold;
            color: #3498db;
            letter-spacing: 5px;
            font-family: 'Courier New', monospace;
        }}
        .message {{
            color: #555;
            margin: 20px 0;
        }}
        .footer {{
            text-align: center;
            color: #777;
            font-size: 12px;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
        }}
        .warning {{
            color: #e74c3c;
            font-size: 14px;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{title}</h1>
        </div>
        
        <p>Hello {name},</p>
        
        <p class="message">{message}</p>
        
        <div class="code-box">
            <p style="margin: 0; color: #666; font-size: 14px;">Your verification code is:</p>
            <p class="code">{verification_code}</p>
        </div>
        
        <p style="color: #e74c3c; text-align: center;">{expiry}</p>
        
        <p class="warning">
            If you didn't request this, please ignore this email.
        </p>
        
        <div class="footer">
            <p>Best regards,<br>The U-Finder Team</p>
        </div>
    </div>
</body>
</html>
"""


async def _render_email_template(template_name: str, context: dict[str, str]) -> Optional[str]:
    """Load an HTML template file and replace known placeholders."""
    template_dir = Path(__file__).resolve().parents[1] / "templates" / "emails"
    template_path = template_dir / template_name

    if not template_path.exists():
        logger.warning(f"Email template not found: {template_path}")
        return None

    try:
        async with aiofiles.open(template_path, "r", encoding="utf-8") as f:
            template_content = await f.read()
    except Exception as e:
        logger.error(f"Failed to read email template {template_path}: {str(e)}")
        return None

    rendered = template_content
    for key, value in context.items():
        safe_value = escape(value, quote=True)
        rendered = rendered.replace(f"{{{{{key}}}}}", safe_value)
        rendered = rendered.replace(f"{{{{ {key} }}}}", safe_value)

    return rendered


async def _save_email_to_file(
    to_email: str,
    verification_code: str,
    name: str,
    email_type: str,
    html_content: str
) -> bool:
    """
    Save email to file for development/testing
    
    Args:
        to_email: Recipient email
        verification_code: Verification code
        name: User name
        email_type: Email type
        html_content: HTML content of email
    
    Returns:
        bool: True if saved successfully
    """
    try:
        # Create emails directory if it doesn't exist
        email_dir = Path("dev_emails")
        email_dir.mkdir(exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{email_type}_{to_email.replace('@', '_')}_{timestamp}.html"
        filepath = email_dir / filename
        
        # Create email preview with metadata
        email_preview = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Email Preview - {email_type}</title>
    <style>
        .metadata {{
            background: #f0f0f0;
            padding: 20px;
            border-radius: 5px;
            margin-bottom: 20px;
            font-family: monospace;
        }}
        .metadata h2 {{
            margin-top: 0;
            color: #333;
        }}
        .metadata p {{
            margin: 5px 0;
        }}
        .code-highlight {{
            background: #fff3cd;
            padding: 10px;
            border-left: 4px solid #ffc107;
            margin: 10px 0;
            font-size: 18px;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <div class="metadata">
        <h2>📧 Development Email Preview</h2>
        <p><strong>To:</strong> {to_email}</p>
        <p><strong>Type:</strong> {email_type}</p>
        <p><strong>Name:</strong> {name}</p>
        <p><strong>Time:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        <div class="code-highlight">
            🔐 Verification Code: {verification_code}
        </div>
    </div>
    <hr>
    {html_content}
</body>
</html>
"""
        
        # Save to file
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            await f.write(email_preview)
        
        logger.info(f"📧 [DEV MODE] Email saved to: {filepath}")
        logger.info(f"🔐 Verification code for {to_email}: {verification_code}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to save email to file: {str(e)}")
        return False
