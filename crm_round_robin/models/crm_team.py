from odoo import models, fields, api
from odoo.tools.safe_eval import safe_eval
import logging

_logger = logging.getLogger(__name__)


class CrmTeam(models.Model):
    _inherit = 'crm.team'

    rr_last_user_id = fields.Many2one(
        comodel_name='res.users',
        string='Last Assigned (Round Robin)',
        help='Internal tracker — do not edit manually.',
        copy=False,
    )

    # Odoo 19 built-in cron ei method call kore                           
    @api.model
    def _rr_cron_assign_leads(self):
        _logger.info('Round Robin CRON: started.')
        teams = self.search([('active', '=', True)])
        for team in teams:
            count = team._assign_unassigned_leads_round_robin()
            if count:
                team.message_post(
                    body=f'Round Robin (Auto): {count} lead(s) assigned. '
                         f'Last: {team.rr_last_user_id.name or "N/A"}'
                )

      
    def action_assign_leads(self):
        total = 0
        for team in self:
            count = team._assign_unassigned_leads_round_robin()
            team.message_post(
                body=f'Round Robin (Manual): {count} lead(s) assigned. '
                     f'Last: {team.rr_last_user_id.name or "N/A"}'
            )
            total += count

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Round Robin Assignment',
                'message': f'{total} lead(s) assigned successfully.',
                'type': 'success',
                'sticky': False,
            },
        }

    # Core round-robin logic                                 
    def _assign_unassigned_leads_round_robin(self):
        self.ensure_one()

        #  Active members 
        active_members = self.env['crm.team.member'].search([
            ('crm_team_id', '=', self.id),
            ('active', '=', True),
        ])
        active_users = active_members.mapped('user_id').filtered(
            lambda u: u.active
        ).sorted(key=lambda u: u.id)

        if not active_users:
            _logger.info('Round Robin: team "%s" — no active members.', self.name)
            return 0

        #  Parse assignment_domain 
        raw_domain = self.assignment_domain
        _logger.info('Round Robin: team "%s" raw domain=%r type=%s',
                     self.name, raw_domain, type(raw_domain).__name__)

        if not raw_domain:
            team_domain = []
        elif isinstance(raw_domain, (list, tuple)):
            team_domain = list(raw_domain)
        elif isinstance(raw_domain, str):
            try:
                team_domain = safe_eval(raw_domain)
            except Exception:
                _logger.warning('Round Robin: domain parse failed.')
                team_domain = []
        else:
            team_domain = []

        _logger.info('Round Robin: team "%s" parsed domain=%s', self.name, team_domain)

        #  Search unassigned leads 
        base_domain = [
            ('user_id', '=', False),
            ('active', '=', True),
        ]
        full_domain = base_domain + team_domain
        _logger.info('Round Robin: team "%s" full_domain=%s', self.name, full_domain)

        leads = self.env['crm.lead'].search(full_domain, order='id asc')
        _logger.info('Round Robin: team "%s" found %s leads.', self.name, len(leads))

        if not leads:
            return 0

        #  Starting index 
        last_user = self.rr_last_user_id
        user_ids_list = list(active_users.ids)

        if not last_user or last_user.id not in user_ids_list:
            current_index = 0
        else:
            last_index = user_ids_list.index(last_user.id)
            current_index = (last_index + 1) % len(active_users)

        _logger.info('Round Robin: team "%s" start index=%s user="%s"',
                     self.name, current_index, active_users[current_index].name)

        #  Distribute
        assigned_count = 0
        last_assigned_user = None

        for lead in leads:
            user = active_users[current_index]
            lead.sudo().write({
                'user_id': user.id,
                'team_id': self.id,
                'type': 'opportunity',
            })
            last_assigned_user = user
            _logger.info('Round Robin: "%s" → "%s"', lead.name, user.name)
            assigned_count += 1
            current_index = (current_index + 1) % len(active_users)

        #  Save last assigned 
        if last_assigned_user:
            self.sudo().write({'rr_last_user_id': last_assigned_user.id})
            _logger.info(
                'Round Robin: team "%s" done. assigned=%s last="%s" next="%s"',
                self.name, assigned_count,
                last_assigned_user.name,
                active_users[current_index].name,
            )

        return assigned_count