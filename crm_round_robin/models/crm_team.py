
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class CrmTeam(models.Model):


    _inherit = 'crm.team'

    #  remembers the last member who received a lead            
    rr_last_user_id = fields.Many2one(
        comodel_name='res.users',
        string='Last Assigned (Round Robin)',
        help='Internal tracker — do not edit manually. '
             'Stores which team member was assigned a lead last so the '
             'next round-robin pick starts from the following member.',
        copy=False,
    )

    #  Scheduled action entry point                                        
    @api.model
    def _cron_assign_leads_round_robin(self):
        
        _logger.info('Round Robin Cron: starting lead assignment run.')
        active_teams = self.search([('active', '=', True)])
        total_assigned = 0
        for team in active_teams:
            count = team._assign_unassigned_leads_round_robin()
            total_assigned += count
        _logger.info(
            'Round Robin Cron: finished. Total leads assigned: %s.',
            total_assigned,
        )

    #  "Assign Leads" button action                                        
    def action_assign_leads_round_robin(self):
        """
        Called when the user clicks the "Assign Leads" button on the
        Sales Team form view.  Processes only the current team.
        """
        self.ensure_one()
        count = self._assign_unassigned_leads_round_robin()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Round Robin Assignment',
                'message': f'{count} lead(s) assigned successfully.',
                'type': 'success',
                'sticky': False,
            },
        }

    #  Core distribution logic (per team)                                  
    def _assign_unassigned_leads_round_robin(self):
        
        self.ensure_one()

        # Collect active members (stable sort by user id)
        active_members = self.env['crm.team.member'].search([
            ('crm_team_id', '=', self.id),
            ('active', '=', True),
        ])
        active_users = active_members.mapped('user_id').filtered(
            lambda u: u.active
        ).sorted(key=lambda u: u.id)

        if not active_users:
            _logger.info(
                'Round Robin: team "%s" has no active members — skipped.',
                self.name,
            )
            return 0

        #Build lead search domain 
        base_domain = [
            ('team_id', '=', self.id),
            ('user_id', '=', False),
            ('active', '=', True),
        ]

        # Merge the team's own Assignment Rules domain (if any)
        team_domain = self.assignment_domain or []
        if isinstance(team_domain, str):
            # Stored as string in some Odoo versions — safe eval
            from odoo.tools.safe_eval import safe_eval
            team_domain = safe_eval(team_domain)

        full_domain = base_domain + team_domain

        leads = self.env['crm.lead'].search(full_domain, order='id asc')

        if not leads:
            _logger.info(
                'Round Robin: team "%s" — no unassigned leads match domain.',
                self.name,
            )
            return 0

        _logger.info(
            'Round Robin: team "%s" — found %s unassigned lead(s), '
            '%s active member(s).',
            self.name, len(leads), len(active_users),
        )

        # Determine starting index 
        last_user = self.rr_last_user_id
        user_ids_list = list(active_users.ids)

        if not last_user or last_user.id not in user_ids_list:
            # First run ever, or last user left the team → start at index 0
            current_index = 0
        else:
            last_index = user_ids_list.index(last_user.id)
            current_index = (last_index + 1) % len(active_users)

        # Distribute leads one by one 
        assigned_count = 0
        for lead in leads:
            user = active_users[current_index]
            lead.sudo().write({'user_id': user.id})
            _logger.debug(
                'Round Robin: lead "%s" (id=%s) → user "%s" (id=%s).',
                lead.name, lead.id, user.name, user.id,
            )
            assigned_count += 1
            current_index = (current_index + 1) % len(active_users)

        # current_index is now pointing to the NEXT user; we want to save
        last_assigned_index = (current_index - 1) % len(active_users)
        last_assigned_user = active_users[last_assigned_index]
        self.sudo().write({'rr_last_user_id': last_assigned_user.id})

        _logger.info(
            'Round Robin: team "%s" — assigned %s lead(s). '
            'Last assigned to "%s".',
            self.name, assigned_count, last_assigned_user.name,
        )
        return assigned_count
