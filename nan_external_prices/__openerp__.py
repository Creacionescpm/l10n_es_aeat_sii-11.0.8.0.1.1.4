##############################################################################
#
# Copyright (c) 2010 NaN Projectes de Programari Lliure, S.L.  All Rights Reserved.
#                    http://www.NaN-tic.com
#
# WARNING: This program as such is intended to be used by professional
# programmers who take the whole responsability of assessing all potential
# consequences resulting from its eventual inadequacies and bugs
# End users who are looking for a ready-to-use solution with commercial
# garantees and support are strongly adviced to contract a Free Software
# Service Company
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
##############################################################################

{
    "name" : "External Prices",
    "version" : "3.0",
    "depends" : [
        'account',
        'account_tax_include',
        'sale',
        'stock',
    ],
    "author" : "NaN - Daniel (Avanzosc) - Acysos",
    "description": """\
This module adds new fields in sale orders and invoice lines to store untaxed and tax amounts as created by an external application or online shop. This avoids rounding differences between both applications.

A flag in both sale orders and invoices allows the user to decide what values to use the one of the external application or the ones calculated by OpenERP.
Refactoriced for v6.0""",
    "website" : "http://www.NaN-tic.com, http://www.acysos.com",
    "category" : "Generic Modules",
    "init_xml" : [],
    "demo_xml" : [],
    "update_xml" : [
        'invoice_view.xml',
        'sale_view.xml',
    ],
    "active": False,
    "installable": True,
}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
