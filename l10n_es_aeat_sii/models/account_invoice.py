# -*- coding: utf-8 -*-
# Copyright 2017 Ignacio Ibeas <ignacio@acysos.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from osv import osv, fields
import exceptions
from requests import Session
from zeep import Client
from zeep.transports import Transport
from zeep.plugins import HistoryPlugin
from datetime import datetime
from tools.translate import _


class AccountInvoice(osv.osv):
    _inherit = 'account.invoice'

#     def _get_default_key(self, cr, uid, data, context=None):
#         if context is None:
#             context = {}
# 
#         sii_key_obj = self.pool.get('aeat.sii.mapping.registration.keys')
#         type = context.get('type')
#         if type in ['in_invoice', 'in_refund']:
#             key = sii_key_obj.search(
#                 cr, uid, [('code', '=', '01'), ('type', '=', 'purchase')], limit=1)
#         else:
#             key = sii_key_obj.search(
#                 cr, uid, [('code', '=', '01'), ('type', '=', 'sale')], limit=1)
#         return key and key[0]

    _columns = {
        'sii_description': fields.text(string='SII Description', required=True),
        'sii_sent': fields.boolean(string='SII Sent'),
        'sii_csv': fields.char(string='SII CSV', size=128),
        'sii_return': fields.text(string='SII Return'),
        'refund_type': fields.selection(
            selection=[('S', 'By substitution'), ('I', 'By differences')],
            string="Refund Type"),
        'sii_enabled': fields.related(
            'company_id', 'sii_enabled', type='boolean', relation='res.company',
            string='SII Enabled', store=True, readonly=True),
        'registration_key': fields.many2one(
            'aeat.sii.mapping.registration.keys', "Registration key",
            required=True)
    }

    _defaults = {
        'sii_description': '/'
    }

    def onchange_refund_type(self, cr, uid):
        if self.refund_type == 'S' and not self.origin_invoices_ids:
            self.refund_type = False
            return {'warning':
                {'message': 'Debes tener al menos una factura '
                            'vinculada que sustituir'
                 }
            }

    def onchange_partner_id(self, cr, uid, ids, type, partner_id,
            date_invoice=False, payment_term=False, partner_bank_id=False,
            company_id=False):
        res = super(AccountInvoice, self).onchange_partner_id(
            cr, uid, ids, type, partner_id, date_invoice,
            payment_term, partner_bank_id, company_id)
        values = res['value']
        if values['fiscal_position']:
            fp = self.pool.get('account.fiscal.position').browse(
                cr, uid, values['fiscal_position'])
            if type in ['out_invoice', 'out_refund'] and \
                    fp.sii_registration_key_sale:
                values['registration_key'] = fp.sii_registration_key_sale.id
            if type in ['in_invoice', 'in_refund'] and \
                    fp.sii_registration_key_sale:
                values['registration_key'] = fp.sii_registration_key_purchase.id
            res['value'] = values
        return res

    def create(self, cr, uid, vals, context=None):
        fp = None
        if not vals.get('registration_key', False):
            if vals.get('fiscal_position', False):
                fp = self.pool.get('account.fiscal.position').browse(
                    cr, uid, vals['fiscal_position'])
            if not fp and vals.get('address_invoice_id', False):
                partner = self.pool.get('res.partner.address').browse(
                    cr, uid, vals['address_invoice_id'])
                fp = partner.partner_id.property_account_position
            if not fp and vals.get('partner_id', False):
                partner = self.pool.get('res.partner').browse(
                    cr, uid, vals['partner_id'])
                fp = partner.property_account_position
            if fp:
                if vals['type'] in ['out_invoice', 'out_refund']:
                    vals['registration_key'] = fp.sii_registration_key_sale.id
                if vals['type'] in ['in_invoice', 'in_refund']:
                    vals['registration_key'] = fp.sii_registration_key_purchase.id
        invoice = super(AccountInvoice, self).create(cr, uid, vals, context)
        return invoice

    def map_tax_template(self, cr, uid, tax_template, mapping_taxes, invoice):
        # Adapted from account_chart_update module
        """Adds a tax template -> tax id to the mapping."""
        if not tax_template:
            return None
        if mapping_taxes.get(tax_template):
            return mapping_taxes[tax_template]
        # search inactive taxes too, to avoid re-creating
        # taxes that have been deactivated before
        context = {'active_test': False}
        tax_obj = self.pool.get('account.tax')
        criteria = ['|',
                    ('name', '=', tax_template.name),
                    ('description', '=', tax_template.name)]
        if tax_template.description:
            criteria = ['|', '|'] + criteria
            criteria += [('description', '=', tax_template.description),
                         ('name', '=', tax_template.description)]
        criteria += [('company_id', '=', invoice.company_id.id)]
        taxes = tax_obj.search(cr, uid, criteria, context=context)
        mapping_taxes[tax_template] = (
            taxes and taxes[0] or None)
        return mapping_taxes[tax_template]

    def _get_taxes_map(self, cr, uid, codes, date, invoice):
        # Return the codes that correspond to that sii map line codes
        taxes = []
        sii_map_obj = self.pool.get('aeat.sii.map')
        sii_map_line_obj = self.pool.get('aeat.sii.map.lines')
        sii_map = sii_map_obj.browse(cr, uid, sii_map_obj.search(
            cr, uid,
            ['|', ('date_from', '<=', date), ('date_from', '=', False),
             '|', ('date_to', '>=', date), ('date_to', '=', False)], limit=1)[0])
        mapping_taxes = {}
        for code in codes:
            tax_search = sii_map_line_obj.browse(cr, uid, sii_map_line_obj.search(
                cr, uid, [('code', '=', code), ('sii_map_id', '=', sii_map.id)],
                limit=1)[0])
            tax_templates = tax_search.taxes
            for tax_template in tax_templates:
                tax = self.map_tax_template(cr, uid, tax_template, mapping_taxes, invoice)
                if tax:
                    taxes.append(tax)
        return self.pool.get("account.tax").browse(cr, uid, taxes)

    def _change_date_format(self, cr, uid, date):
        datetimeobject = datetime.strptime(date, '%Y-%m-%d')
        new_date = datetimeobject.strftime('%d-%m-%Y')
        return new_date

    def _get_header(self, cr, uid, ids, company, TipoComunicacion):
        if not company.partner_id.vat:
            raise Warning(_(
                "No VAT configured for the company"))
        id_version_sii = "1.0"
        header = {
            "IDVersionSii": id_version_sii,
            "Titular": {
                "NombreRazon": company.name,
                "NIF": company.partner_id.vat[2:]},
            "TipoComunicacion": TipoComunicacion
        }
        return header

    def _get_tax_line_req(self, cr, uid, tax_type, line, line_taxes):
        taxes = False
        taxes_RE = self._get_taxes_map(
            cr, uid, ['RE'], line.invoice_id.date_invoice, line.invoice_id)
        if len(line_taxes) > 1:
            for tax in line_taxes:
                if tax in taxes_RE:
                    price = line.price_unit * (1 - (
                        line.discount or 0.0) / 100.0)
                    taxes = self.pool.get('account.tax').compute_all(
                        cr, uid, [tax], price, line.quantity, line.product_id,
                        line.invoice_id.partner_id)
                    taxes['percentage'] = tax.amount
                    return taxes
        return taxes

    def _get_sii_tax_line(self, cr, uid, tax_line, line, line_taxes, invoice):
        tax_type = tax_line.amount * 100
        tax_line_req = self._get_tax_line_req(cr, uid, tax_type, line, line_taxes)
        tax = self.pool.get('account.tax').browse(cr, uid, tax_line.id)
        if tax:
            taxes = self.pool.get('account.tax').compute_all(
                cr, uid, [tax],
                (line.price_unit * (1 - (line.discount or 0.0) / 100.0)),
                line.quantity, line.product_id, line.invoice_id.partner_id)
        tax_sii = {
            "TipoImpositivo": tax_type,
            "BaseImponible": taxes['total']
        }
        if tax_line_req:
            tipo_recargo = tax_line_req['percentage'] * 100
            cuota_recargo = tax_line_req['taxes'][0]['amount']
            tax_sii['TipoRecargoEquivalencia'] = tipo_recargo
            tax_sii['CuotaRecargoEquivalencia'] = cuota_recargo

        if invoice.type in ['out_invoice', 'out_refund']:
            tax_sii['CuotaRepercutida'] = taxes['taxes'][0]['amount']
        if invoice.type in ['in_invoice', 'in_refund']:
            tax_sii['CuotaSoportada'] = taxes['taxes'][0]['amount']
        return tax_sii

    def _update_sii_tax_line(self, cr, uid, tax_sii, tax_line, line, line_taxes, invoice):
        tax_type = tax_line.amount * 100
        tax_line_req = self._get_tax_line_req(cr, uid, tax_type, line, line_taxes)
        taxes = self.pool.get('account.tax').compute_all(
            cr, uid, [tax_line],
            (line.price_unit * (1 - (line.discount or 0.0) / 100.0)),
            line.quantity, line.product_id, line.invoice_id.partner_id)
        if tax_line_req:
            TipoRecargo = tax_line_req['percentage'] * 100
            CuotaRecargo = tax_line_req['taxes'][0]['amount']
            tax_sii[str(tax_type)]['TipoRecargoEquivalencia'] += TipoRecargo
            tax_sii[str(tax_type)]['CuotaRecargoEquivalencia'] += CuotaRecargo
        tax_sii[str(tax_type)]['BaseImponible'] += taxes['total']
        if invoice.type in ['out_invoice', 'out_refund']:
            tax_sii[str(tax_type)]['CuotaRepercutida'] += taxes['taxes'][0]['amount']
        if invoice.type in ['in_invoice', 'in_refund']:
            tax_sii[str(tax_type)]['CuotaSoportada'] += taxes['taxes'][0]['amount']
        return tax_sii

    def _get_sii_out_taxes(self, cr, uid, invoice):
        taxes_sii = {}
        taxes_f = {}
        taxes_to = {}
        taxes_sfesb = self._get_taxes_map(cr, uid, ['SFESB'],
                                          invoice.date_invoice, invoice)
        taxes_sfesbe = self._get_taxes_map(
            cr, uid, ['SFESBE'], invoice.date_invoice, invoice)
        taxes_sfesbei = self._get_taxes_map(
            cr, uid, ['SFESBEI'], invoice.date_invoice, invoice)
        taxes_sfesbee = self._get_taxes_map(
            cr, uid, ['SFESBEE'], invoice.date_invoice, invoice)
        taxes_sfesisp = self._get_taxes_map(cr, uid, ['SFESISP'],
                                            invoice.date_invoice, invoice)
        # taxes_sfesisps = self._get_taxes_map(cr, uid, ['SFESISPS'], self.date_invoice, invoice)
        taxes_sfens = self._get_taxes_map(cr, uid, ['SFENS'],
                                          invoice.date_invoice, invoice)
        taxes_sfess = self._get_taxes_map(cr, uid, ['SFESS'],
                                          invoice.date_invoice, invoice)
        taxes_sfesse = self._get_taxes_map(cr, uid, ['SFESSE'],
                                           invoice.date_invoice, invoice)
        for line in invoice.invoice_line:
            for tax_line in line.invoice_line_tax_id:
                if tax_line in taxes_sfesb or tax_line in taxes_sfesisp or \
                        tax_line in taxes_sfens or tax_line in taxes_sfesbe:
                    if 'DesgloseFactura' not in taxes_sii:
                        taxes_sii['DesgloseFactura'] = {}
                    inv_breakdown = taxes_sii['DesgloseFactura']
                    if tax_line in taxes_sfesb or tax_line in taxes_sfesbe:
                        if 'Sujeta' not in inv_breakdown:
                            inv_breakdown['Sujeta'] = {}
                        # TODO l10n_es no tiene impuesto exento de bienes
                        # corrientes nacionales
                        if tax_line in taxes_sfesbe:
                            if 'Exenta' not in inv_breakdown['Sujeta']:
                                inv_breakdown['Sujeta']['Exenta'] = {
                                    'BaseImponible': line.price_subtotal}
                            else:
                                inv_breakdown['Sujeta']['Exenta'][
                                    'BaseImponible'] += line.price_subtotal
                        # TODO Facturas No sujetas
                        if tax_line in taxes_sfesb or \
                                tax_line in taxes_sfesisp:
                            if 'NoExenta' not in inv_breakdown[
                                    'Sujeta']:
                                inv_breakdown['Sujeta'][
                                    'NoExenta'] = {}
                            if tax_line in taxes_sfesisp:
                                tipo_no_exenta = 'S2'
                            else:
                                tipo_no_exenta = 'S1'
                            inv_breakdown['Sujeta']['NoExenta'][
                                'TipoNoExenta'] = tipo_no_exenta
                            if 'DesgloseIVA' not in inv_breakdown[
                                    'Sujeta']['NoExenta']:
                                inv_breakdown['Sujeta'][
                                    'NoExenta']['DesgloseIVA'] = {}
                                inv_breakdown['Sujeta'][
                                    'NoExenta']['DesgloseIVA'][
                                        'DetalleIVA'] = []
                            tax_type = tax_line.amount * 100
                            if str(tax_type) not in taxes_f:
                                taxes_f[str(tax_type)] = \
                                    self._get_sii_tax_line(
                                        cr, uid,
                                        tax_line, line,
                                        line.invoice_line_tax_id, invoice)
                            else:
                                taxes_f = self._update_sii_tax_line(
                                    cr, uid,
                                    taxes_f, tax_line, line,
                                    line.invoice_line_tax_id, invoice)
                if tax_line in taxes_sfess or tax_line in taxes_sfesse or \
                        tax_line in taxes_sfesbee or tax_line in taxes_sfesbei:
                    if 'DesgloseTipoOperacion' not in taxes_sii:
                        taxes_sii['DesgloseTipoOperacion'] = {}
                    type_breakdown = taxes_sii['DesgloseTipoOperacion']
                    if tax_line in taxes_sfess or \
                            tax_line in taxes_sfesse:
                        if 'PrestacionServicios' not in type_breakdown:
                            type_breakdown['PrestacionServicios'] = {}
                        op_key = 'PrestacionServicios'
                    if tax_line in taxes_sfesbee or tax_line in taxes_sfesbei:
                        if 'Entrega' not in type_breakdown:
                            type_breakdown['Entrega'] = {}
                        op_key = 'Entrega'
                    if 'Sujeta' not in type_breakdown[op_key]:
                        type_breakdown[op_key]['Sujeta'] = {}
                    if tax_line in taxes_sfesse or \
                            tax_line in taxes_sfesbee or \
                            tax_line in taxes_sfesbei:
                        if 'Exenta' not in type_breakdown[op_key]['Sujeta']:
                            type_breakdown[op_key]['Sujeta'][
                                'Exenta'] = {
                                    'BaseImponible': line.price_subtotal}
                            if tax_line in taxes_sfesbee:
                                type_breakdown[op_key]['Sujeta']['Exenta'][
                                    'CausaExencion'] = 'E2'
                            if tax_line in taxes_sfesbei:
                                type_breakdown[op_key]['Sujeta']['Exenta'][
                                    'CausaExencion'] = 'E5'
                        else:
                            type_breakdown[op_key]['Sujeta']['Exenta'][
                                'BaseImponible'] += line.price_subtotal
                    # TODO Facturas no sujetas
                    if tax_line in taxes_sfess:
                        if 'NoExenta' not in type_breakdown[
                                'PrestacionServicios']['Sujeta']:
                            type_breakdown['PrestacionServicios'][
                                'Sujeta']['NoExenta'] = {}
                            # TODO l10n_es_ no tiene impuesto ISP de servicios
                            # if tax_line in taxes_sfesisps:
                            #     TipoNoExenta = 'S2'
                            # else:
                            tipo_no_exenta = 'S1'
                            type_breakdown[
                                'PrestacionServicios']['º']['NoExenta'][
                                    'TipoNoExenta'] = tipo_no_exenta
                        if 'DesgloseIVA' not in taxes_sii[
                            'DesgloseTipoOperacion']['PrestacionServicios'][
                                'Sujeta']['NoExenta']:
                            type_breakdown[
                                'PrestacionServicios']['Sujeta']['NoExenta'][
                                    'DesgloseIVA'] = {}
                            type_breakdown[
                                'PrestacionServicios']['Sujeta']['NoExenta'][
                                    'DesgloseIVA']['DetalleIVA'] = []
                            tax_type = tax_line.amount * 100
                            if str(tax_type) not in taxes_to:
                                taxes_to[str(tax_type)] = \
                                    self._get_sii_tax_line(
                                        cr, uid, tax_line, line,
                                        line.invoice_line_tax_id, invoice)
                            else:
                                taxes_to = self._update_sii_tax_line(
                                    cr, uid, taxes_to, tax_line, line,
                                    line.invoice_line_tax_id, invoice)
        if len(taxes_f) > 0:
            if invoice.type == 'out_refund' and invoice.refund_type == 'I':
                for key, line in taxes_f.iteritems():
                    line['BaseImponible'] = -round(line['BaseImponible'],2)
                    line['CuotaRepercutida'] = -round(
                        line['CuotaRepercutida'],2)
                    taxes_sii['DesgloseFactura']['Sujeta']['NoExenta'][
                        'DesgloseIVA']['DetalleIVA'].append(line)
            else:
                for key, line in taxes_f.iteritems():
                    line['BaseImponible'] = round(line['BaseImponible'],2)
                    line['CuotaRepercutida'] = round(line['CuotaRepercutida'],2)
                    taxes_sii['DesgloseFactura']['Sujeta']['NoExenta'][
                        'DesgloseIVA']['DetalleIVA'].append(line)
        if len(taxes_to) > 0:
            if invoice.type == 'out_refund' and invoice.refund_type == 'I':
                for key, line in taxes_to.iteritems():
                    line['BaseImponible'] = -round(line['BaseImponible'],2)
                    line['CuotaRepercutida'] = -round(
                        line['CuotaRepercutida'],2)
                    taxes_sii['DesgloseTipoOperacion']['PrestacionServicios'][
                        'Sujeta']['NoExenta']['DesgloseIVA'][
                            'DetalleIVA'].append(line)
            else:
                for key, line in taxes_to.iteritems():
                    line['BaseImponible'] = round(line['BaseImponible'],2)
                    line['CuotaRepercutida'] = round(line['CuotaRepercutida'],2)
                    taxes_sii['DesgloseTipoOperacion']['PrestacionServicios'][
                        'Sujeta']['NoExenta']['DesgloseIVA'][
                            'DetalleIVA'].append(line)
        return taxes_sii

    def _get_sii_in_taxes(self, cr, uid, invoice):
        taxes_sii = {}
        taxes_f = {}
        taxes_isp = {}
        taxes_sfrs = self._get_taxes_map(cr, uid, ['SFRS'],
                                         invoice.date_invoice, invoice)
        taxes_sfrisp = self._get_taxes_map(cr, uid, ['SFRISP'],
                                           invoice.date_invoice, invoice)
        for line in invoice.invoice_line:
            for tax_line in line.invoice_line_tax_id:
                if tax_line in taxes_sfrs or tax_line in taxes_sfrisp:
                    if tax_line in taxes_sfrisp:
                        if 'InversionSujetoPasivo' not in taxes_sii:
                            taxes_sii['InversionSujetoPasivo'] = {}
                            taxes_sii['InversionSujetoPasivo'][
                                'DetalleIVA'] = []
                        tax_type = tax_line.amount * 100
                        if tax_type not in taxes_isp:
                            taxes_isp[str(tax_type)] = self._get_sii_tax_line(
                                cr, uid,
                                tax_line, line, line.invoice_line_tax_id, invoice)
                        else:
                            taxes_isp = self._update_sii_tax_line(
                                cr, uid, taxes_isp, tax_line, line,
                                line.invoice_line_tax_id, invoice)
                    else:
                        if 'DesgloseIVA' not in taxes_sii:
                            taxes_sii['DesgloseIVA'] = {}
                            taxes_sii['DesgloseIVA'][
                                'DetalleIVA'] = []
                        tax_type = tax_line.amount * 100
                        if str(tax_type) not in taxes_f:
                            taxes_f[str(tax_type)] = self._get_sii_tax_line(
                                cr, uid,
                                tax_line, line, line.invoice_line_tax_id, invoice)
                        else:
                            taxes_f = self._update_sii_tax_line(
                                cr, uid,
                                taxes_f, tax_line, line,
                                line.invoice_line_tax_id, invoice)
        if len(taxes_f) > 0:
            if invoice.type == 'in_refund' and invoice.refund_type == 'I':
                for key, line in taxes_f.iteritems():
                    line['BaseImponible'] = -round(line['BaseImponible'],2)
                    line['CuotaSoportada'] = -round(line['CuotaSoportada'],2)
                    taxes_sii['DesgloseIVA']['DetalleIVA'].append(line)
            else:
                for key, line in taxes_f.iteritems():
                    line['BaseImponible'] = round(line['BaseImponible'],2)
                    line['CuotaSoportada'] = round(line['CuotaSoportada'],2)
                    taxes_sii['DesgloseIVA']['DetalleIVA'].append(line)
        if len(taxes_isp) > 0:
            if invoice.type == 'in_refund' and invoice.refund_type == 'I':
                for key, line in taxes_isp.iteritems():
                    line['BaseImponible'] = -round(line['BaseImponible'],2)
                    line['CuotaSoportada'] = -round(line['CuotaSoportada'],2)
                    taxes_sii['InversionSujetoPasivo']['DetalleIVA'].append(
                        line)
            else:
                for key, line in taxes_isp.iteritems():
                    line['BaseImponible'] = round(line['BaseImponible'],2)
                    line['CuotaSoportada'] = round(line['CuotaSoportada'],2)
                    taxes_sii['InversionSujetoPasivo']['DetalleIVA'].append(
                        line)
        return taxes_sii

    def _get_invoices(self, cr, uid, company, invoice):
        if not invoice.partner_id.vat:
            raise Warning(_("The partner has not a VAT configured."))
        invoice_date = self._change_date_format(cr, uid, invoice.date_invoice)
        ejercicio = invoice.period_id.fiscalyear_id.date_start[0:4]
        periodo = invoice.period_id.date_start[5:7]
        if not company.chart_template_id:
            raise exceptions.Warning(_(
                'You have to select what account chart template use this'
                ' company.'))
        key = invoice.registration_key.code
        if invoice.type in ['out_invoice', 'out_refund']:
            tipo_factura = 'F1'
            #           TODO Los 5 tipos de facturas rectificativas
            if invoice.type == 'out_refund':
                tipo_factura = 'R4'
            tipo_desglose = self._get_sii_out_taxes(cr, uid, invoice)
            if invoice.type == 'out_refund' and invoice.refund_type == 'I':
                    importe_total = -abs(invoice.amount_total)
            else:
                importe_total = invoice.amount_total
            invoices = {
                "IDFactura": {
                    "IDEmisorFactura": {
                        "NIF": company.partner_id.vat[2:]
                    },
                    "NumSerieFacturaEmisor": invoice.number[0:60],
                    "FechaExpedicionFacturaEmisor": invoice_date},
                "PeriodoImpositivo": {
                    "Ejercicio": ejercicio,
                    "Periodo": periodo
                },
                "FacturaExpedida": {
                    "TipoFactura": tipo_factura,
                    "ClaveRegimenEspecialOTrascendencia": key,
                    "DescripcionOperacion": invoice.sii_description[0:500],
                    "Contraparte": {
                        "NombreRazon": invoice.partner_id.name[0:120],
                    },
                    "TipoDesglose": tipo_desglose,
                    "ImporteTotal": importe_total
                }
            }
            invoices['FacturaExpedida']['Contraparte'].update(
                self._get_sii_identifier(cr, uid, invoice))
            if invoice.type == 'out_refund':
                invoices['FacturaExpedida'][
                    'TipoRectificativa'] = invoice.refund_type
                if invoice.refund_type == 'S':
                    base_rectificada = 0
                    cuota_rectificada = 0
                    for s in invoice.origin_invoices_ids:
                        base_rectificada += s.amount_untaxed
                        cuota_rectificada += s.amount_tax
                    invoices['FacturaExpedida']['ImporteRectificacion'] = {
                        'BaseRectificada': base_rectificada,
                        'CuotaRectificada': cuota_rectificada
                    }

        if invoice.type in ['in_invoice', 'in_refund']:
            #           TODO Los 5 tipos de facturas rectificativas
            tipo_facturea = 'F1'
            if invoice.type == 'in_refund':
                tipo_facturea = 'R4'
            desglose_factura = self._get_sii_in_taxes(cr, uid, invoice)
            cuota_deducible = 0
#             cuota_deducible = invoice.amount_tax
            if 'DesgloseIVA' in desglose_factura:
                for desglose in desglose_factura['DesgloseIVA']['DetalleIVA']:
                    cuota_deducible += desglose['CuotaSoportada']
            invoices = {
                "IDFactura": {
                    "IDEmisorFactura": {
                    },
                    "NumSerieFacturaEmisor": invoice.reference[
                        0:60],
                    "FechaExpedicionFacturaEmisor": invoice_date},
                "PeriodoImpositivo": {
                    "Ejercicio": ejercicio,
                    "Periodo": periodo
                },
                "FacturaRecibida": {
                    "TipoFactura": tipo_facturea,
                    "ClaveRegimenEspecialOTrascendencia": key,
                    "DescripcionOperacion": invoice.sii_description[0:500],
                    "DesgloseFactura": desglose_factura,
                    "Contraparte": {
                        "NombreRazon": invoice.partner_id.name[0:120],
                    },
                    "FechaRegContable": invoice_date,
                    "CuotaDeducible": round(cuota_deducible, 2)
                }
            }
            id_emisor = self._get_sii_identifier(cr, uid, invoice)
            invoices['IDFactura']['IDEmisorFactura'].update(id_emisor)
            invoices['FacturaRecibida']['Contraparte'].update(id_emisor)
            if invoice.type == 'in_refund':
                invoices['FacturaRecibida'][
                    'TipoRectificativa'] = invoice.refund_type

                if invoice.refund_type == 'S':
                    base_rectificada = 0
                    cuota_rectificada = 0
                    for s in invoice.origin_invoices_ids:
                        base_rectificada += s.amount_untaxed
                        cuota_rectificada += s.amount_tax
                    invoices['FacturaRecibida']['ImporteRectificacion'] = {
                        'BaseRectificada': base_rectificada,
                        'CuotaRectificada': cuota_rectificada
                    }
        return invoices

    def _connect_sii(self, cr, uid, wsdl):
        publicCrt = self.pool.get('ir.config_parameter').get_param(
            cr, uid, 'l10n_es_aeat_sii.publicCrt', False)
        privateKey = self.pool.get('ir.config_parameter').get_param(
            cr, uid, 'l10n_es_aeat_sii.privateKey', False)

        session = Session()
        session.cert = (publicCrt, privateKey)
        transport = Transport(session=session)

        history = HistoryPlugin()
        client = Client(wsdl=wsdl, transport=transport, plugins=[history])
        return client

    def _send_invoice_to_sii(self, cr, uid, ids):
        for invoice in self.pool.get('account.invoice').browse(cr, uid, ids):
            company = invoice.company_id
            port_name = ''
            try:
                if invoice.type in ['out_invoice', 'out_refund']:
                    wsdl = self.pool.get('ir.config_parameter').get_param(cr, uid,
                        'l10n_es_aeat_sii.wsdl_out', False)
                    client = self._connect_sii(cr, uid, wsdl)
                    port_name = 'SuministroFactEmitidas'
                    if company.sii_test:
                        port_name += 'Pruebas'
                elif invoice.type in ['in_invoice', 'in_refund']:
                    wsdl = self.pool.get('ir.config_parameter').get_param(cr, uid,
                        'l10n_es_aeat_sii.wsdl_in', False)
                    client = self._connect_sii(cr, uid, wsdl)
                    port_name = 'SuministroFactRecibidas'
                    if company.sii_test:
                        port_name += 'Pruebas'
                serv = client.bind('siiService', port_name)
                if not invoice.sii_sent:
                    tipo_comunicacion = 'A0'
                else:
                    tipo_comunicacion = 'A1'
                header = self._get_header(cr, uid, invoice.id, company,
                                          tipo_comunicacion)
                invoices = self._get_invoices(cr, uid, company, invoice)
                if invoice.type in ['out_invoice', 'out_refund']:
                    res = serv.SuministroLRFacturasEmitidas(
                        header, invoices)
                elif invoice.type in ['in_invoice', 'in_refund']:
                    res = serv.SuministroLRFacturasRecibidas(
                        header, invoices)
                # TODO Facturas intracomunitarias 66 RIVA
                # elif invoice.fiscal_position.id == self.env.ref(
                #     'account.fp_intra').id:
                #     res = serv.SuministroLRDetOperacionIntracomunitaria(
                #         header, invoices)
                if res['EstadoEnvio'] in ['Correcto', 'ParcialmenteCorrecto']:
                    return_vals = {'sii_sent': True, 'sii_csv': res['CSV'],
                                   'sii_return': res}
                else:
                    return_vals = {'sii_sent': False, 'sii_return': res}
                self.write(cr, uid, invoice.id, return_vals)
            except Exception as fault:
                self.write(cr, uid, invoice.id, {'sii_return': fault})

    def action_number(self, cr, uid, ids, context=None):
        res = super(AccountInvoice, self).action_number(cr, uid, ids, context=context)
        for invoice in self.browse(cr, uid, ids):
            company = invoice.company_id
            if company.sii_enabled and company.sii_method == 'auto':
                self._send_invoice_to_sii(cr, uid, [invoice.id])
        return res

    def send_sii(self, cr, uid, ids, context=None):
        for invoice in self.browse(cr, uid, ids):
            company = invoice.company_id
            if company.sii_enabled and company.sii_method == 'auto':
                self._send_invoice_to_sii(cr, uid, [invoice.id])
        return True

    def copy(self, cr, uid, id, default, context={}):

        default['sii_sent'] = False
        default['sii_csv'] = None
        default['sii_return'] = None

        return super(AccountInvoice, self).copy(cr, uid, id, default,
                                                context=context)

    def _fix_country_code(self, cr, uid, dic_ret, context=None):
        if dic_ret['IDOtro']['CodigoPais'] == 'UK':
            dic_ret['IDOtro']['CodigoPais'] = 'GB'
        return dic_ret

    def _get_sii_identifier(self, cr, uid, invoice, context=None):
        dic_ret = {}
        vat = ''.join(e for e in invoice.partner_id.vat if e.isalnum()).upper()
        if invoice.fiscal_position.name == u'Régimen Intracomunitario':
            dic_ret = {
                "IDOtro": {
                    "CodigoPais":
                        invoice.address_invoice_id.country_id and
                        invoice.address_invoice_id.country_id.code or
                        vat[:2],
                    "IDType": '02',
                    "ID": vat
                }
            }
            dic_ret = self._fix_country_code(cr, uid, dic_ret, context)
        elif invoice.fiscal_position.name == \
                u'Régimen Extracomunitario':
            dic_ret = {
                "IDOtro": {
                    "CodigoPais":
                        invoice.address_invoice_id.country_id and
                        invoice.address_invoice_id.country_id.code or
                        vat[:2],
                    "IDType": '04',
                    "ID": vat
                  }
            }
            dic_ret = self._fix_country_code(cr, uid, dic_ret, context)
        elif vat.startswith('ESN'):
            dic_ret = {"NIF": invoice.partner_id.vat[2:]}
        else:
            dic_ret = {"NIF": invoice.partner_id.vat[2:]}
        return dic_ret

AccountInvoice()

