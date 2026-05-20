# -*- coding: utf-8 -*-
"""
Shared helpers for the Helpdesk Student REST API.

Responsibilities
----------------
- Bearer / API-key authentication decorator
- Partner resolution from student e-mail
- Uniform JSON response builders  (success / error)
- Ticket serialisers              (list item vs. full detail)
"""

import json
import logging
from functools import wraps

from odoo.exceptions import AccessError
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

def _json_response(data: dict, status: int = 200) -> Response:
    return Response(
        json.dumps(data, default=str),
        status=status,
        content_type='application/json; charset=utf-8',
    )


def success_response(data, *, meta: dict = None) -> Response:
    payload = {'status': 'success', 'data': data}
    if meta:
        payload['meta'] = meta
    return _json_response(payload, 200)


def error_response(http_status: int, code: str, message: str) -> Response:
    return _json_response(
        {'status': 'error', 'error': {'code': code, 'message': message}},
        http_status,
    )


# ---------------------------------------------------------------------------
# Authentication decorator
# ---------------------------------------------------------------------------

def require_api_key(fn):
    """
    Validate  ``Authorization: Bearer <key>``  against Odoo's built-in
    ``res.users.apikeys`` table (scope = 'rpc').

    On success  → re-scopes ``request.env`` to the key owner and calls fn.
    On failure  → returns a 401 JSON response immediately.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.httprequest.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return error_response(
                401, 'MISSING_AUTH',
                'Authorization header required. '
                'Format: "Authorization: Bearer <api_key>"',
            )

        raw_key = auth_header[len('Bearer '):]

        try:
            uid = (
                request.env['res.users.apikeys']
                .sudo()
                ._check_credentials(scope='rpc', key=raw_key)
            )
        except (AccessError, ValueError):
            uid = None

        if not uid:
            return error_response(
                401, 'INVALID_API_KEY',
                'API key is invalid or has been revoked.',
            )

        request.update_env(user=uid)
        _logger.debug('API key resolved → uid=%s', uid)
        return fn(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Partner resolution  (by student e-mail)
# ---------------------------------------------------------------------------

def resolve_partner_by_email(email: str):
    """
    Return the first ``res.partner`` whose e-mail matches *email*
    (case-insensitive exact match).

    Returns the partner record on success, or ``None`` when not found.
    Uses ``sudo()`` so the API key owner's access level never blocks the
    look-up of portal / public partner records.
    """
    if not email or not email.strip():
        return None
    Partner = request.env['res.partner'].sudo()
    partner = Partner.search([
        ('email', '=', email.strip()),
    ], limit=1)
    return partner or None


# ---------------------------------------------------------------------------
# Datetime helper
# ---------------------------------------------------------------------------

def _fmt_dt(dt) -> str | None:
    """ISO-8601 UTC string, or None."""
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


# ---------------------------------------------------------------------------
# Ticket serialisers
# ---------------------------------------------------------------------------

def serialize_ticket_list_item(ticket) -> dict:
    """
    Lightweight payload used in the **list** endpoint.

    Fields: id, ticket_ref, subject, status, create_date.
    """
    return {
        'id':          ticket.id,
        'create_date': _fmt_dt(ticket.create_date),
        # 'ticket_ref':  ticket.ticket_ref or f'HD{ticket.id:05d}',
        'status':      ticket.stage_id.name if ticket.stage_id else None,
        'subject':     ticket.name,
    }


def serialize_ticket_detail(ticket) -> dict:
    """
    Full payload used in the **detail** endpoint.

    Fields: id, ticket_ref, subject, status, create_date,
            team, description, communication_history, attachments.
    """
    return {
        'id':                    ticket.id,
        # 'ticket_ref':            ticket.ticket_ref or f'HD{ticket.id:05d}',
        'subject':               ticket.name,
        'status':                ticket.stage_id.name  if ticket.stage_id  else None,
        'create_date':           _fmt_dt(ticket.create_date),
        'team':                  ticket.team_id.name   if ticket.team_id   else None,
        'description':           ticket.description or '',
        'communication_history': _get_messages(ticket),
         'attachments':           _get_attachments(ticket),
    }


# ---------------------------------------------------------------------------
# Internal serialisation helpers
# ---------------------------------------------------------------------------

def _get_messages(ticket) -> list[dict]:
    """
    Return human-written chatter messages for the ticket, oldest first.

    Included:   message_type in ('comment', 'email', 'email_outgoing')
                with a non-empty body.
    Excluded:   automated notifications, system log-notes, empty messages.
    """
    messages = ticket.message_ids.filtered(
        lambda m: (
            m.message_type in ('comment', 'email', 'email_outgoing')
            and bool((m.body or '').strip())
        )
    ).sorted('date')

    result = []
    for msg in messages:
        result.append({
            'id':           msg.id,
            'date':         _fmt_dt(msg.date),
            'author':       msg.author_id.name if msg.author_id else 'Unknown',
            'author_id':    msg.author_id.id   if msg.author_id else None,
            'message_type': msg.message_type,
            'body':         msg.body,
            'attachments': [
                {
                    'id':       att.id,
                    'name':     att.name,
                    'mimetype': att.mimetype,
                    'url':      f'/web/content/{att.id}?download=true',
                }
                for att in msg.attachment_ids
            ],
        })

    return result


def _get_attachments(ticket) -> list[dict]:
    """
    All ``ir.attachment`` records linked directly to this ticket record.
    """
    attachments = (
        request.env['ir.attachment']
        .sudo()
        .search([
            ('res_model', '=', 'helpdesk.ticket'),
            ('res_id',    '=', ticket.id),
        ])
    )

    return [
        {
            'id':          att.id,
            'name':        att.name,
            'mimetype':    att.mimetype,
            'file_size':   att.file_size,
            'url':         f'/web/content/{att.id}?download=true',
            'create_date': _fmt_dt(att.create_date),
        }
        for att in attachments
    ]
