# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2011 - 2013 Therp BV (<http://therp.nl>).
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

"""
This module adds support for Direct debit orders as applicable
in the Netherlands. Debit orders are advanced in total by the bank.
Amounts that cannot be debited or are canceled by account owners are
credited afterwards. Such a creditation is called a storno.

Invoice workflow:

1 the sale leads to 
   1300 Debtors 100
   8000 Sales       100

Balance: 
  Debtors  2000 | 
  Sales        | 2000

2 an external booking takes place
   1100 Bank    100
   1300 Debtors     100
   This booking is reconciled with [1]
   The invoice gets set to state 'paid', and 'reconciled' = True

Balance:
   Debtors 1900 |
   Bank     100 |
   Sales        | 2000

This module implements the following diversion:

2a the invoice is included in a direct debit order. When the order is
   confirmed, a move is created per invoice:

   2000 Transfer account 100 |
   1300 Debtors              | 100
   Reconciliation takes place between 1 and 2a. 
   The invoice gets set to state 'paid', and 'reconciled' = True

Balance:
   Debtors             0 |  
   Transfer account 2000 |
   Bank                0 |
   Sales                 | 2000

3a the direct debit order is booked on the bank account

Balance:
  1100 Bank             2000 |
  2000 Transfer account      | 2000
  Reconciliation takes place between 3a and 2a

Balance:
   Debtors             0 |  
   Transfer account    0 |
   Bank             2000 |
   Sales                 | 2000

4 a storno from invoice [1] triggers a new booking on the bank account
  1300 Debtors 100 |
  1100 Bank        | 100
  
Balance:
   Debtors           100 |  
   Transfer account    0 |
   Bank             1900 |
   Sales                 | 2000

   The reconciliation of 2a is undone. The booking of 2a is reconciled 
   with the booking of 4 instead.
   The payment line attribute 'storno' is set to True and the invoice
   state is no longer 'paid'.

Two cases need to be distinguisted:
   1) If the storno is a manual storno from the partner, the invoice is set to
      state 'debit_denied', with 'reconciled' = False 
      This module implements this option by allowing the bank module to call
     
          netsvc.LocalService("workflow").trg_validate(
              uid, 'account.invoice', ids, 'debit_denied', cr)

   2) If the storno is an error generated by the bank (assumingly non-fatal),
      the invoice is reopened for the next debit run. This is a call to existing
     
         netsvc.LocalService("workflow").trg_validate(
             uid, 'account.invoice', ids, 'open_test', cr)

      Should also be adding a log entry on the invoice for tracing purposes

         self._log_event(cr, uid, ids, -1.0, 'Debit denied')           

      If not for that funny comment
      "#TODO: implement messages system"  in account/invoice.py

   Repeating non-fatal fatal errors need to be dealt with manually by checking
   open invoices with a matured invoice- or due date.
""" 

class account_invoice(osv.osv):
    _inherit = "account.invoice"

    def __init__(self, pool, cr):
        """ 
        Adding a state to the hardcoded state list of the inherited
        model. The alternative is duplicating the field definition 
        in columns but only one module can do that!

        Maybe apply a similar trick when overriding the buttons' 'states' attributes
        in the form view, manipulating the xml in fields_view_get().
        """ 
        super(account_invoice, self).__init__(pool, cr)
        invoice_obj = pool.get('account.invoice')
        invoice_obj._columns['state'].selection.append(
            ('debit_denied', 'Debit denied'))

    def action_debit_denied(self, cr, uid, ids, context=None):
        for invoice_id in ids:
            if self.test_paid(cr, uid, [invoice_id], context):
                number = self.read(
                    cr, uid, invoice_id, ['number'], context=context)['number']
                raise osv.except_osv(
                    _('Error !'), 
                    _('You cannot set invoice \'%s\' to state \'debit denied\', ' +
                      'as it is still reconciled.') % number)
        self.write(cr, uid, ids, {'state': 'debit_denied'}, context=context)
        for inv_id, name in self.name_get(cr, uid, ids, context=context):
            message = _("Invoice '%s': direct debit is denied.") % name
            self.log(cr, uid, inv_id, message)
        return True

    def test_undo_debit_denied(self, cr, uid, ids, context=None):
        """ 
        Called from the workflow. Used to unset paid state on
        invoices that were paid with bank transfers which are being cancelled 
        """
        for invoice in self.read(cr, uid, ids, ['reconciled'], context):
            if not invoice['reconciled']:
                return False
        return True

account_invoice()