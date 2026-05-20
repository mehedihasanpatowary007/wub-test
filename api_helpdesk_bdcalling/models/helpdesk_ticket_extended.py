from odoo import models, fields

class HelpdeskTicketExtended(models.Model):
    _inherit = 'helpdesk.ticket'

    team_id = fields.Many2one(
        'helpdesk.team', 
        string='Helpdesk Team',
        required=False,
    )