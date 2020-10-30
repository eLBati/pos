from odoo import models, _
from odoo.tools import float_round


class Order(models.Model):
    _inherit = 'pos.order'

    def _prepare_account_move_and_lines(self, session=None, move=None):
        vals = super(Order, self)._prepare_account_move_and_lines(session, move)
        grouped_data = vals['grouped_data']
        all_lines = []
        for group_key, group_data in grouped_data.items():
            for value in group_data:
                all_lines.append(value)
        if all_lines:
            grouped_lines = self._group_lines_by_tax(all_lines)
            vals['grouped_data'] = {}
            for idx, line in enumerate(grouped_lines):
                # the key is not used later
                vals['grouped_data'][line['name'] + ' ' + str(idx)] = [line]
        return vals

    @staticmethod
    def _check_grouping_applicability(lines):
        date_maturity = False
        tax_line_id_account_id = False
        tax_ids_account_id = False
        for line in lines:
            if line.get('date_maturity'):
                if date_maturity and date_maturity != line['date_maturity']:
                    return False
                date_maturity = line['date_maturity']
            if line.get('tax_line_id'):
                if (
                    tax_line_id_account_id and
                    tax_line_id_account_id != line['account_id']
                ):
                    return False
                tax_line_id_account_id = line['account_id']
            if line.get('tax_ids'):
                if (
                    tax_ids_account_id and
                    tax_ids_account_id != line['account_id']
                ):
                    return False
                tax_ids_account_id = line['account_id']
        return True

    @staticmethod
    def _get_grouped_lines(all_lines):
        grouped_lines = {}
        counter_part_lines = []
        for line in all_lines:
            tax_line_id = line.get('tax_line_id')
            tax_ids = line.get('tax_ids', [])
            if len(tax_ids) > 1:
                # Can't handle multiple operations
                return None, None
            tax_ids = tax_ids[0][2] if tax_ids else []
            if tax_line_id or tax_ids:
                if len(tax_ids) > 1 or line.get('analytic_account_id'):
                    # Impossible to do the group computation in this cases
                    return None, None
                if tax_line_id:
                    key = tax_line_id
                elif tax_ids:
                    key = tax_ids[0]
                if key not in grouped_lines:
                    grouped_lines[key] = [line]
                else:
                    grouped_lines[key].append(line)
            else:
                counter_part_lines.append(line)
        return grouped_lines, counter_part_lines

    def _group_lines_by_tax(self, all_lines):
        grouped_lines, counter_part_lines = self._get_grouped_lines(all_lines)
        if not grouped_lines:
            return all_lines
        precision = self[0].company_id.currency_id.decimal_places
        new_lines = []
        for key in grouped_lines:
            tax = self.env['account.tax'].browse(key)
            lines = grouped_lines[key]
            if not self._check_grouping_applicability(lines):
                new_lines.extend(lines)
                continue
            for line in lines:
                if line.get('tax_ids'):
                    untaxed_account_id = line['account_id']
                if line.get('tax_line_id'):
                    tax_account_id = line['account_id']
            date_maturity = lines[0].get('date_maturity')
            total = 0
            for line in lines:
                if line.get('debit'):
                    total -= line['debit']
                elif line.get('credit'):
                    total += line['credit']
            untaxed_amount = float_round(
                total / (1 + (tax.amount / 100)), precision_digits=precision)
            tax_amount = total - untaxed_amount
            new_lines.append({
                'name': _("%s: untaxed amount") % tax.name,
                'account_id': untaxed_account_id,
                'date_maturity': date_maturity,
                'tax_ids': [(6, 0, [tax.id])],
                'debit': untaxed_amount if untaxed_amount < 0 else 0,
                'credit': untaxed_amount if untaxed_amount > 0 else 0,
            })
            new_lines.append({
                'name': _("%s: tax") % tax.name,
                'account_id': tax_account_id,
                'date_maturity': date_maturity,
                'tax_line_id': tax.id,
                'debit': tax_amount if tax_amount < 0 else 0,
                'credit': tax_amount if tax_amount > 0 else 0,
            })
        for counter_part_line in counter_part_lines:
            new_lines.append(counter_part_line)
        return new_lines
