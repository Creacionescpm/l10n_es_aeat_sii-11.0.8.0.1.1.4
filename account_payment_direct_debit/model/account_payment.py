# -*- coding: utf-8 -*-
from osv import fields, osv
import netsvc
from tools.translate import _

class payment_order(osv.osv):
    _inherit = 'payment.order'

    def test_undo_done(self, cr, uid, ids, context=None):
        """ 
        Called from the workflow. Used to unset done state on
        payment orders that were reconciled with bank transfers
        which are being cancelled 
        """
        for order in self.browse(cr, uid, ids, context=context):
            if order.type == 'receivable':
                for line in order.line_ids:
                    if line.storno:
                        return False
        return super(payment_order, self).test_undo_done(
            cr, uid, ids, context=context)
payment_order()
