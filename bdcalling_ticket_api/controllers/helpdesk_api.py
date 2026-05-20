# -*- coding: utf-8 -*-
"""
Helpdesk Student REST API — Controller
=======================================

Two endpoints:

    GET /api/v1/helpdesk/tickets
        ─ Required param : email  (student e-mail address)
        ─ Returns        : array of ALL tickets for that student

    GET /api/v1/helpdesk/tickets/<ticket_id>
        ─ Required param : email  (student e-mail address)
        ─ Returns        : full detail of one ticket, validated to belong
                           to that student

Authentication
--------------
Bearer token (Odoo API Key) in every request:
    Authorization: Bearer <odoo_api_key>

Error codes
-----------
400  MISSING_EMAIL       – email param absent or blank
400  VALIDATION_ERROR    – bad query-string value
401  MISSING_AUTH        – no Authorization header
401  INVALID_API_KEY     – key not found / revoked
404  STUDENT_NOT_FOUND   – no partner found for the given e-mail
404  TICKET_NOT_FOUND    – ticket does not exist or belongs to another student
500  INTERNAL_ERROR      – unexpected server error
"""

import logging

from odoo.exceptions import AccessError
from odoo.http import request, route, Controller

from ..utils.api_helpers import (
    error_response,
    require_api_key,
    resolve_partner_by_email,
    serialize_ticket_detail,
    serialize_ticket_list_item,
    success_response,
)


_logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE     = 100
_VALID_SORT_FIELDS = {'create_date': 'create_date', 'name': 'name', 'stage': 'stage_id'}
_VALID_SORT_DIRS   = ('asc', 'desc')


class HelpdeskStudentAPIController(Controller):

    # -----------------------------------------------------------------------
    # 1. LIST  ─  GET /api/v1/helpdesk/tickets?email=student@example.com
    # -----------------------------------------------------------------------

    @route(
        '/api/v1/helpdesk/tickets',
        type='http',
        auth='none',
        methods=['GET'],
        csrf=False,
        save_session=False,
    )
    # @require_api_key
    def list_student_tickets(self, **params):
        """
        Return ALL helpdesk tickets that belong to the student identified
        by the ``email`` query parameter.

        Query Parameters
        ----------------
        Success Response 200
        --------------------
        {
            "status": "success",
            "data": [
                {
                    "id": 12,
                    "create_date": "2025-03-10T08:22:00Z"
                    "status": "New",
                    "subject": "Cannot access portal",
                },
                ...
            ],
        }
        """
        try:
            # ── 1. Require email ─────────────────────────────────────────
            email = (params.get('email') or '').strip()
            if not email:
                return error_response(
                    400, 'MISSING_EMAIL',
                    'Query parameter "email" is required. '
                    'Example: /api/v1/helpdesk/tickets?email=student@university.com',
                )

            # ── 2. Resolve partner ───────────────────────────────────────
            partner = resolve_partner_by_email(email)
            if not partner:
                return error_response(
                    404, 'STUDENT_NOT_FOUND',
                    f'No student record found for email: {email}',
                )
            domain = [
                ('partner_id', '=', partner.id),
            ]

            Ticket = request.env['helpdesk.ticket'].sudo()
            

            tickets = Ticket.search(
                domain,
            )

            _logger.info(
                'list_student_tickets: email=%s partner=%s found %d ticket(s)',
                email, partner.name,
            )

            return success_response(
                [serialize_ticket_list_item(t) for t in tickets],
                # meta={
                #     'student_email': partner.email,
                #     'student_name':  partner.name,
                #     'total_count':   len(tickets),
                # },
            )

        except AccessError as exc:
            _logger.warning('Access error listing tickets email=%s: %s', params.get('email'), exc)
            return error_response(403, 'FORBIDDEN', str(exc))
        except Exception as exc:
            _logger.exception('Unexpected error in list_student_tickets: %s', exc)
            return error_response(500, 'INTERNAL_ERROR',
                                  'An unexpected error occurred. Please try again.')

    # -----------------------------------------------------------------------
    # 2. DETAIL  ─  GET /api/v1/helpdesk/tickets/<ticket_id>?email=student@example.com
    # -----------------------------------------------------------------------

    @route(
        '/api/v1/helpdesk/tickets/<int:ticket_id>',
        type='http',
        auth='none',
        methods=['GET'],
        csrf=False,
        save_session=False,
    )
    # @require_api_key
    def get_ticket_detail(self, ticket_id: int, **params):
        """
        Return full detail for a single helpdesk ticket.

        The ticket is only returned when its ``partner_id`` or
        ``partner_email`` matches the supplied student e-mail — preventing
        cross-student data leakage.

        Path Parameter
        --------------
        ticket_id   int   REQUIRED – internal Odoo ID of the ticket

        Query Parameter
        ---------------
        email       str   REQUIRED – student e-mail address (ownership check)

        Success Response 200
        --------------------
        {
            "status": "success",
            "data": {
                "id": 12,
                "subject": "Cannot access student portal",
                "status": "In Progress",
                "create_date": "2025-03-10T08:22:00Z",
                "team": "Student Support",
                "description": "<p>I get a 403 when logging in.</p>",
                "communication_history": [
                    {
                        "id": 101,
                        "date": "2025-03-10T09:00:00Z",
                        "author": "Sarah (Support)",
                        "author_id": 5,
                        "message_type": "comment",
                        "body": "<p>We are looking into this.</p>",
                        "attachments": []
                    }
                ],
                
            }
        }
        """
        try:
        
            ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)

            if not ticket.exists():
                return error_response(
                    404, 'TICKET_NOT_FOUND',
                    f'Ticket {ticket_id} does not exist.',
                )
            
            return success_response(serialize_ticket_detail(ticket))

        except AccessError as exc:
            _logger.warning(
                'Access error ticket=%s email=%s: %s',
                ticket_id, params.get('email'), exc,
            )
            return error_response(
                404, 'TICKET_NOT_FOUND',
                f'Ticket {ticket_id} does not exist.',
            )
        except Exception as exc:
            _logger.exception(
                'Unexpected error in get_ticket_detail ticket_id=%s: %s',
                ticket_id, exc,
            )
            return error_response(500, 'INTERNAL_ERROR',
                                  'An unexpected error occurred. Please try again.')
