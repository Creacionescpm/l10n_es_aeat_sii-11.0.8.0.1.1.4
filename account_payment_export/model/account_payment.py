# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2009 EduSense BV (<http://www.edusense.nl>).
#              (C) 2011 - 2013 Therp BV (<http://therp.nl>).
#            
#    All other contributions are (C) by their respective contributors
#
#    All Rights Reserved
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from osv import fields, osv
from tools.translate import _
import netsvc


class payment_order(osv.osv):
    _inherit = 'payment.order'

    def launch_wizard(self, cr, uid, ids, context=None):
        """
        Search for a wizard to launch according to the type.
        If type is manual. just confirm the order.
        Previously (pre-v6) in account_payment/wizard/wizard_pay.py
        """
        if context == None:
            context = {}
        result = {}
        orders = self.browse(cr, uid, ids, context)
        order = orders[0]
        # check if a wizard is defined for the first order
        if order.mode.type and order.mode.type.ir_model_id:
            context['active_ids'] = ids
            wizard_model = order.mode.type.ir_model_id.model
            wizard_obj = self.pool.get(wizard_model)
            wizard_id = wizard_obj.create(cr, uid, {}, context)
            result = {
                'name': wizard_obj._description or _('Payment Order Export'),
                'view_type': 'form',
                'view_mode': 'form',
                'res_model': wizard_model,
                'domain': [],
                'context': context,
                'type': 'ir.actions.act_window',
                'target': 'new',
                'res_id': wizard_id,
                'nodestroy': True,
                }
        else:
            # should all be manual orders without type or wizard model
            for order in orders[1:]:
                if order.mode.type and order.mode.type.ir_model_id:
                    raise osv.except_osv(
                        _('Error'),
                        _('You can only combine payment orders of the same type')
                        )
            # process manual payments
            wf_service = netsvc.LocalService('workflow')
            for order_id in ids:
                wf_service.trg_validate(uid, 'payment.order', order_id, 'done', cr)
	    return True
        return result
    
payment_order()
    
class payment_type(osv.osv):
    _inherit = 'payment.type'
    
    _columns = {
        'ir_model_id': fields.many2one(
            'ir.model', 'Payment wizard',
            help=('Select the Payment Wizard for payments of this type. '
                  'Leave empty for manual processing'),
            domain=[('osv_memory', '=', True)],
            ),
    }
payment_type()
