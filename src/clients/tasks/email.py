"""
Celery tasks for bulk email sending.
"""
from celery import shared_task
from django.conf import settings
from email.mime.image import MIMEImage
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, ignore_result=True, name='clients.tasks.send_bulk_email_task')
def send_bulk_email_task(self, recipients=None, subject='', message='', from_email='',
                         send_as_html=False, broadcast_id=None,
                         recipient_group='', extra_params=None):
    """
    Send bulk email. Two calling modes:
      1. recipients=[...] — explicit list (used by attachment/sync path)
      2. recipient_group='contacts_all' + extra_params={...} — task resolves the list
         (used by the async no-attachment path; keeps the view instant)
    Updates EmailBroadcast log when done.
    Uses a single persistent SMTP connection to avoid Gmail rate-limiting.
    """
    import re
    from django.core.mail import EmailMessage, get_connection
    from clients.models import EmailBroadcast

    # Resolve recipient list from group if not provided directly
    if recipients is None:
        from atletasworld.admin_views import _resolve_recipient_emails
        extra = extra_params or {}
        resolved = _resolve_recipient_emails(
            recipient_group,
            package_id=extra.get('package_id', ''),
            contact_source=extra.get('contact_source', ''),
            individual_emails=extra.get('individual_emails') or [],
        )
        recipients = list(resolved)
        if broadcast_id:
            try:
                EmailBroadcast.objects.filter(id=broadcast_id).update(
                    recipient_emails=','.join(recipients)
                )
            except Exception as e:
                logger.warning(f"send_bulk_email_task: could not update recipient_emails: {e}")

    if not recipients:
        logger.warning(f"send_bulk_email_task: no recipients for group '{recipient_group}'")
        if broadcast_id:
            EmailBroadcast.objects.filter(id=broadcast_id).update(sent_count=0, failed_count=0)
        return "No recipients"

    sent_count = 0
    failed_count = 0

    site_url = settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'https://atletasperformancecenter.com'

    # Build body once — it's identical for every recipient
    if send_as_html:
        html_message = message.replace('\n', '<br>')
        body = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif; line-height: 1.6; color: #333333; background-color: #f5f5f5; margin: 0; padding: 0; }}
    .email-wrapper {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; }}
    .email-header {{ background: linear-gradient(135deg, #1a1a1a 0%, #2c3e50 100%); padding: 30px; text-align: center; }}
    .email-header img {{ max-height: 60px; width: auto; }}
    .email-header h1 {{ color: #ffffff; margin: 12px 0 0 0; font-size: 22px; font-weight: 600; letter-spacing: 0.5px; }}
    .email-body {{ padding: 40px 30px; }}
    .email-body p {{ margin: 0 0 15px 0; color: #555555; }}
    .divider {{ border: none; border-top: 1px solid #eeeeee; margin: 30px 0; }}
    .signature {{ font-size: 14px; color: #444444; }}
    .signature strong {{ color: #1a1a1a; font-size: 15px; }}
    .signature .title {{ color: #888888; font-size: 13px; margin: 2px 0; }}
    .signature .contact {{ color: #888888; font-size: 13px; margin: 2px 0; }}
    .signature .contact a {{ color: #1a1a1a; text-decoration: none; }}
    .signature-bar {{ width: 40px; height: 3px; background-color: #D7FF00; margin: 10px 0; }}
    .email-footer {{ background-color: #1a1a1a; padding: 25px 30px; text-align: center; }}
    .email-footer p {{ color: #888888; font-size: 12px; margin: 4px 0; }}
    .email-footer a {{ color: #D7FF00; text-decoration: none; }}
</style>
</head>
<body>
<div class="email-wrapper">
    <div class="email-header">
        <a href="{site_url}" target="_blank" style="display:inline-block;"><img src="{site_url}/static/img/apc-logo-yellow.png" alt="Atletas Performance Center" onerror="this.style.display=\'none\'" style="border:0;"></a>
    </div>
    <div class="email-body">
        {html_message}
        <hr class="divider">
        <div class="signature">
            <div class="signature-bar"></div>
            <strong>Atletas Performance Center</strong><br>
            <div class="title">High Performance &amp; Athletic Development</div>
            <div class="contact">📧 <a href="mailto:info@atletasperformancecenter.com">info@atletasperformancecenter.com</a></div>
            <div class="contact">🌐 <a href="{site_url}">{site_url.replace("https://", "")}</a></div>
        </div>
    </div>
    <div class="email-footer">
        <a href="{site_url}" target="_blank" style="display:inline-block;"><img src="{site_url}/static/img/apc-logo-yellow.png" alt="Atletas Performance Center" height="36" style="height:36px;width:auto;display:inline-block;border:0;margin-bottom:8px;"></a>
        <p>
            <a href="https://www.instagram.com/atletasperformancecenter/" target="_blank">Instagram</a> &nbsp;|&nbsp;
            <a href="https://www.facebook.com/profile.php?id=61572009236369" target="_blank">Facebook</a>
        </p>
        <p style="margin-top: 8px;">
            <a href="{site_url}/portal/notifications/" style="color:#aaaaaa;font-size:11px;">Manage Notification Preferences</a>
            &nbsp;|&nbsp;
            <a href="__UNSUBSCRIBE_URL__" style="color:#aaaaaa;font-size:11px;">Unsubscribe</a>
        </p>
        <p style="margin-top: 12px; font-size: 11px; color: #555555;">
            &copy; 2026 Atletas Performance Center. All rights reserved.
        </p>
    </div>
</div>
</body>
</html>'''
    else:
        body = message + (
            f"\n\n--\nAtletas Performance Center\nHigh Performance & Athletic Development\n"
            f"info@atletasperformancecenter.com\n{site_url}\n"
            f"Manage preferences: {site_url}/portal/notifications/\n"
            f"Unsubscribe: __UNSUBSCRIBE_URL__"
        )

    # Load attachment file data from disk (saved by the view before dispatching to Celery)
    extra = extra_params or {}
    attachment_files = []   # list of (name, data, content_type)
    inline_image_file = None  # (name, data, content_type)

    for att_info in extra.get('attachments') or []:
        try:
            with open(att_info['path'], 'rb') as fh:
                attachment_files.append((att_info['name'], fh.read(), att_info['content_type']))
        except Exception as e:
            logger.warning(f"send_bulk_email_task: could not read attachment {att_info.get('path')}: {e}")

    img_info = extra.get('inline_image')
    if img_info:
        try:
            with open(img_info['path'], 'rb') as fh:
                inline_image_file = (img_info['name'], fh.read(), img_info['content_type'])
        except Exception as e:
            logger.warning(f"send_bulk_email_task: could not read inline_image {img_info.get('path')}: {e}")

    import time
    send_delay = getattr(settings, 'BULK_EMAIL_SEND_DELAY', 0.5)

    # Reuse one SMTP connection for all recipients to avoid Gmail rate-limiting
    connection = get_connection()
    try:
        connection.open()
    except Exception as e:
        logger.error(f"send_bulk_email_task: failed to open SMTP connection: {e}")
        if broadcast_id:
            EmailBroadcast.objects.filter(id=broadcast_id).update(
                sent_count=0, failed_count=len(recipients))
        return f"Sent 0, failed {len(recipients)} (SMTP connection failed)"

    try:
        from clients.models import EmailSuppression, make_unsubscribe_url
        for email_addr in recipients:
            # Skip malformed addresses (commas, spaces, missing domain dot)
            if not re.match(r'^[^@\s,]+@[^@\s,]+\.[^@\s,]+$', email_addr):
                failed_count += 1
                logger.warning(f"send_bulk_email_task: skipping malformed address: {email_addr!r}")
                continue

            # Honor the universal opt-out — never email anyone who unsubscribed.
            if EmailSuppression.is_suppressed(email_addr):
                logger.info(f"send_bulk_email_task: skipping unsubscribed address: {email_addr!r}")
                continue

            # Substitute the per-recipient one-click unsubscribe link.
            try:
                unsub_url = make_unsubscribe_url(email_addr, site_url)
            except Exception:
                unsub_url = f"{site_url}/portal/notifications/"
            recipient_body = body.replace('__UNSUBSCRIBE_URL__', unsub_url)

            try:
                if inline_image_file or (send_as_html and attachment_files):
                    # HTML email with inline image or HTML + attachments
                    this_body = recipient_body
                    if inline_image_file:
                        img_name, img_data, img_ctype = inline_image_file
                        img_tag = '<img src="cid:inline_image" style="max-width:100%;height:auto;margin:20px 0"><br><br>'
                        # Inject image tag before body content
                        this_body = this_body.replace('<div class="email-body">', f'<div class="email-body">{img_tag}', 1)
                    email_msg = EmailMessage(subject=subject, body=this_body,
                                             from_email=from_email, to=[email_addr],
                                             connection=connection)
                    email_msg.content_subtype = 'html'
                    if inline_image_file:
                        img_name, img_data, img_ctype = inline_image_file
                        mime_image = MIMEImage(img_data)
                        mime_image.add_header('Content-ID', '<inline_image>')
                        mime_image.add_header('Content-Disposition', 'inline', filename=img_name)
                        email_msg.attach(mime_image)
                    for att_name, att_data, att_ctype in attachment_files:
                        email_msg.attach(att_name, att_data, att_ctype)
                else:
                    email_msg = EmailMessage(subject=subject, body=recipient_body,
                                             from_email=from_email, to=[email_addr],
                                             connection=connection)
                    if send_as_html:
                        email_msg.content_subtype = 'html'
                    for att_name, att_data, att_ctype in attachment_files:
                        email_msg.attach(att_name, att_data, att_ctype)
                email_msg.send(fail_silently=False)
                sent_count += 1
                if send_delay > 0:
                    time.sleep(send_delay)
            except Exception as e:
                failed_count += 1
                logger.error(f"send_bulk_email_task: failed to send to {email_addr}: {e}")
                # Reopen connection in case it was dropped
                try:
                    connection.close()
                    connection.open()
                except Exception:
                    pass
    finally:
        try:
            connection.close()
        except Exception:
            pass

    # Clean up temp files saved by the view
    import os
    for att_info in extra.get('attachments') or []:
        try:
            os.unlink(att_info['path'])
        except Exception:
            pass
    if img_info:
        try:
            os.unlink(img_info['path'])
        except Exception:
            pass

    if broadcast_id:
        try:
            EmailBroadcast.objects.filter(id=broadcast_id).update(
                sent_count=sent_count,
                failed_count=failed_count,
            )
        except Exception as e:
            logger.error(f"send_bulk_email_task: failed to update broadcast log {broadcast_id}: {e}")

    logger.info(f"send_bulk_email_task: sent={sent_count} failed={failed_count} broadcast_id={broadcast_id}")
    return f"Sent {sent_count}, failed {failed_count}"
