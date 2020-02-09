# -*- coding: utf-8 -*-
# Copyright (C) 2014 GRAP (http://www.grap.coop)
# @author: Sylvain LE GAL (https://twitter.com/legalsylvain)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import os
import logging
import base64
from datetime import datetime

from openerp import tools
from openerp.osv import fields
from openerp.osv.orm import Model
from openerp.tools import image_resize_image

_logger = logging.getLogger(__name__)

try:
    from ftplib import FTP
except ImportError:
    _logger.warning(
       "Cannot import 'ftplib' Python Librairy. 'sp_product_to_scale_bizerba'"
       " module will not work properly.")


class product_scale_log(Model):
    _name = 'product.scale.log'
    _inherit = 'ir.needaction_mixin'
    _order = 'log_date desc, id desc'

    _EXTERNAL_SIZE_ID_RIGHT = 4

    _DELIMITER = '#'

    _ACTION_SELECTION = [
        ('create', 'Creation'),
        ('write', 'Update'),
        ('unlink', 'Deletion'),
    ]

    _ACTION_MAPPING = {
        'create': 'C',
        'write': 'C',
        'unlink': 'S',
    }

    _ENCODING_MAPPING = {
        'iso-8859-1': '\r\n',
        'cp1252': '\n',
        'utf-8': '\n',
    }

    _TRANSLATED_TERM = {0x2018:0x27,
                        0x2019:0x27,
                        0x201C:0x22,
                        0x201D:0x22}

    _EXTERNAL_TEXT_ACTION_CODE = 'C'

    _EXTERNAL_TEXT_DELIMITER = '#'

    # Private Section
    def _clean_value(self, value, product_line):
        if not value:
            return ''
        elif product_line.multiline_length:
            res = ''
            current_val = value
            while current_val:
                res += current_val[:product_line.multiline_length]
                current_val = current_val[product_line.multiline_length:]
                if current_val:
                    res += product_line.multiline_separator
        else:
            res = value
        if product_line.delimiter:
            return res.replace(product_line.delimiter, '')
        else:
            return res

    def _generate_external_text(self, value, product_line, external_id, log):
        external_text_list = [
            self._EXTERNAL_TEXT_ACTION_CODE,                    # WALO Code
            log.product_id.scale_group_id.external_identity,    # ABNR Code
            external_id,                                        # TXNR Code
            self._clean_value(value, product_line),             # TEXT Code
        ]
        return self._EXTERNAL_TEXT_DELIMITER.join(external_text_list)

    # Compute Section
    def _compute_text(
            self, cr, uid, ids, field_name, arg, context=None):
        res = {}
        for log in self.browse(cr, uid, ids, context):

            group = log.product_id.scale_group_id
            product_text =\
                self._ACTION_MAPPING[log.action] + self._DELIMITER
            external_texts = []

            # Set custom fields
            for product_line in group.scale_system_id.product_line_ids:
                if product_line.field_id:
                    value = getattr(log.product_id, product_line.field_id.name)

                if product_line.type == 'id':
                    product_text += str(log.product_id.id)

                elif product_line.type == 'numeric':
                    value = tools.float_round(
                        value * product_line.numeric_coefficient,
                        precision_rounding=product_line.numeric_round)
                    product_text += str(value).replace('.0', '')

                elif product_line.type == 'text':
                    # Supercoop Hack: concatene le code barre base + le nom de produit
                    # Dans l'execution du script,
                    if product_line.code == 'ABEZ':
                        product_text += '%BARCODEBASE%'

                    if product_line.code == 'EAN1':
                        barcode_base = self._clean_value(value, product_line)[4:7]
                        product_text = product_text.replace('%BARCODEBASE%', barcode_base + ' - ')

                    product_text += self._clean_value(value, product_line)
                    # _logger.info('*************%s::%s', product_line.name, product_text)

                elif product_line.type == 'external_text':
                    external_id = str(log.product_id.id)\
                        + str(product_line.id).rjust(
                            self._EXTERNAL_SIZE_ID_RIGHT, '0')
                    external_texts.append(self._generate_external_text(
                        value, product_line, external_id, log))
                    product_text += external_id

                elif product_line.type == 'constant':
                    product_text += self._clean_value(
                        product_line.constant_value, product_line)

                elif product_line.type == 'external_constant':
                    # Constant Value are like product ID = 0
                    external_id = str(product_line.id)

                    external_texts.append(self._generate_external_text(
                        product_line.constant_value, product_line, external_id,
                        log))
                    product_text += external_id

                elif product_line.type == 'many2one':
                    # If the many2one is defined
                    if value and not product_line.related_field_id:
                        product_text += value.id
                    elif value and product_line.related_field_id:
                        item_value = getattr(
                            value, product_line.related_field_id.name)
                        product_text +=\
                            item_value and str(item_value) or ''

                elif product_line.type == 'many2many':
                    # Select one value, depending of x2many_range
                    if product_line.x2many_range < len(value):
                        item = value[product_line.x2many_range - 1]
                        if product_line.related_field_id:
                            item_value = getattr(
                                item, product_line.related_field_id.name)
                        else:
                            item_value = item.id
                        product_text += self._clean_value(
                            item_value, product_line)

                elif product_line.type == 'product_image':
                    product_text += self._generate_image_file_name(
                        cr, uid, log.product_id, product_line.field_id,
                        product_line.suffix or '.PNG',
                        context=context)

                if product_line.delimiter:
                    product_text += product_line.delimiter
            break_line = self._ENCODING_MAPPING[log.scale_system_id.encoding]
            res[log.id] = {
                'product_text': product_text + break_line,
                'external_text': break_line.join(external_texts) + break_line,
                'external_text_display': '\n'.join(
                    [x.replace('\n', '') for x in external_texts]),
            }
        return res

    # Column Section
    _columns = {
        'log_date': fields.datetime('Log Date', required=True),
        'scale_system_id': fields.many2one(
            'product.scale.system', string='Scale System', required=True),
        'product_id': fields.many2one(
            'product.product', string='Product'),
        'product_text': fields.function(
            _compute_text, type='text', string='Product Text',
            multi='compute_text', store={'product.scale.log': (
                lambda self, cr, uid, ids, context=None:
                    ids, ['scale_system_id', 'product_id'], 10)}),
        'external_text': fields.function(
            _compute_text, type='text', string='External Text',
            multi='compute_text', store={'product.scale.log': (
                lambda self, cr, uid, ids, context=None: ids, [
                    'scale_system_id', 'product_id', 'product_id'], 10)}),
        'external_text_display': fields.function(
            _compute_text, type='text', string='External Text (Display)',
            multi='compute_text', store={'product.scale.log': (
                lambda self, cr, uid, ids, context=None: ids, [
                    'scale_system_id', 'product_id', 'product_id'], 10)}),
        'action': fields.selection(
            _ACTION_SELECTION, string='Action', required=True),
        'sent': fields.boolean(string='Is Sent'),
        'last_send_date': fields.datetime('Last Send Date'),
    }

    # View Section
    def _needaction_count(self, cr, uid, domain=None, context=None):
        return len(
            self.search(cr, uid, [('sent', '=', False)], context=context))

    def ftp_connection_open(self, cr, uid, scale_system, context=None):
        """Return a new FTP connection with found parameters."""
        _logger.info("Trying to connect to ftp://%s@%s:%d" % (
            scale_system.ftp_login, scale_system.ftp_host,
            scale_system.ftp_port))
        try:
            ftp = FTP()
            ftp.connect(scale_system.ftp_host, scale_system.ftp_port)
            if scale_system.ftp_login:
                ftp.login(
                    scale_system.ftp_login,
                    scale_system.ftp_password)
            else:
                ftp.login()
            return ftp
        except:
            _logger.error("Connection to ftp://%s@%s:%d failed." % (
                scale_system.ftp_login, scale_system.ftp_host,
                scale_system.ftp_port))
            return False

    def ftp_connection_close(self, cr, uid, ftp, context=None):
        try:
            ftp.quit()
        except:
            pass

    def ftp_connection_push_text_file(
            self, cr, uid, ftp, distant_folder_path, local_folder_path,
            pattern, lines, encoding, context=None):
        if lines:
            # Generate temporary file
            f_name = datetime.now().strftime(pattern)
            local_path = os.path.join(local_folder_path, f_name)
            distant_path = os.path.join(distant_folder_path, f_name)
            f = open(local_path, 'w')
            for line in lines:
                raw_text = line
                if encoding != 'utf-8':
                    raw_text = raw_text.translate(self._TRANSLATED_TERM)
                f.write(raw_text.encode(encoding, errors='ignore'))
            f.close()

            # Send File by FTP
            f = open(local_path, 'r')
            ftp.storbinary('STOR ' + distant_path, f)
            f.close()
            # Delete temporary file
            os.remove(local_path)

    def ftp_connection_push_image_file(self, cr, uid, ftp,
                                       distant_folder_path, local_folder_path,
                                       obj, field, extension, context=None):

        # Generate temporary image file
        f_name = self._generate_image_file_name(
            cr, uid, obj, field, extension, context=context)
        if not f_name:
            # No image define
            return False
        local_path = os.path.join(local_folder_path, f_name)
        distant_path = os.path.join(distant_folder_path, f_name)
        image_base64 = getattr(obj, field.name)
        # Resize and save image
        ext = extension.replace('.', '')
        image_resize_image(
            base64_source=image_base64, size=(120, 120), encoding='base64',
            filetype=ext)
        image_data = base64.b64decode(image_base64)
        f = open(local_path, 'wb')
        f.write(image_data)
        f.close()

        # Send File by FTP
        f = open(local_path, 'r')
        ftp.storbinary('STOR ' + distant_path, f)
        f.close()
        # Delete temporary file
        os.remove(local_path)

    def send_log(self, cr, uid, ids, context=None):
        config_obj = self.pool['ir.config_parameter']
        folder_path = config_obj.get_param(
            cr, uid, 'bizerba.local_folder_path', context=context)

        system_map = {}
        for log in self.browse(cr, uid, ids, context=context):
            if log.scale_system_id in system_map.keys():
                system_map[log.scale_system_id].append(log)
            else:
                system_map[log.scale_system_id] = [log]

        for scale_system, logs in system_map.iteritems():

            # Open FTP Connection
            ftp = self.ftp_connection_open(
                cr, uid, logs[0].scale_system_id, context=context)
            if not ftp:
                return False

            # Generate and Send Files
            now = datetime.now()
            product_text_lst = []
            external_text_lst = []

            for log in logs:
                if log.product_text:
                    product_text_lst.append(log.product_text)
                if log.external_text:
                    external_text_lst.append(log.external_text)
                # Push First Image for constrains reason
                # Image extension will get on the line field suffix
                # for default will be `png` if suffix empty.
                for product_line in scale_system.product_line_ids:
                    if product_line.type == 'product_image' and \
                            scale_system.send_images:
                        # send product image
                        self.ftp_connection_push_image_file(
                            cr, uid, ftp,
                            scale_system.product_image_relative_path,
                            folder_path, log.product_id,
                            product_line.field_id,
                            product_line.suffix or '.PNG',
                            context=context)

            self.ftp_connection_push_text_file(
                cr, uid, ftp, scale_system.csv_relative_path,
                folder_path, scale_system.external_text_file_pattern,
                external_text_lst, scale_system.encoding, context=context)
            self.ftp_connection_push_text_file(
                cr, uid, ftp, scale_system.csv_relative_path,
                folder_path, scale_system.product_text_file_pattern,
                product_text_lst, scale_system.encoding, context=context)

            # Supercoop hack : Generate Key file
            # Ne prend pas le groupe 7. Aucun
            logging.info('Generate Key file')
            query = ('select scale_sequence from product_product pp '
                     'join product_template template2 on pp.product_tmpl_id = template2.id '
                     'where template2.sale_ok = true and scale_group_id != 7 and scale_sequence between 281 and 980')
            cr.execute(query)
            scs = [x[0] for x in cr.fetchall()]

            # Si la touche n'a pas d'assignation, on lui assigne l'article 9999
            # Bien sûr l'article 9999 ne doit pas exister sur la balance
            key_text_lst = []
            for i in range(281, 981):
                r = 9999
                if i in scs:
                    r = i
                line = str(i) + self._EXTERNAL_TEXT_DELIMITER + "0001" + self._EXTERNAL_TEXT_DELIMITER \
                    + str(r) + self._ENCODING_MAPPING[scale_system.encoding]
                key_text_lst.append(line.decode('unicode-escape'))
            # logging.info("%s %s %s %s %s", scale_system.csv_relative_path,
            #              folder_path, scale_system.product_text_file_pattern.replace("ARTI", "KEYS"),
            #              key_text_lst, scale_system.encoding)

            self.ftp_connection_push_text_file(
                cr, uid, ftp, scale_system.csv_relative_path,
                folder_path, scale_system.product_text_file_pattern.replace("ARTI", "KEYS"),
                key_text_lst, scale_system.encoding, context=context)

            # Close FTP Connection
            self.ftp_connection_close(cr, uid, ftp, context=context)

            # Mark logs as sent
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.write(
                cr, uid, [log.id for log in logs], {
                    'sent': True,
                    'last_send_date': now,
                }, context=context)
        return True

    def cron_send_to_scale(self, cr, uid, context=None):
        log_ids = self.search(
            cr, uid, [('sent', '=', False)], order='log_date', context=context)

        # Supercoop hack : Reorder products by name
        if len(log_ids) > 0:
            psg = self.pool['product.scale.group']
            cr.execute('select id from product_scale_group where active = true and id != 7')
            scs = [x[0] for x in cr.fetchall()]
            psg.reorder_products_by_name(cr, uid, scs, context=None)

            log_ids = self.search(
                cr, uid, [('sent', '=', False)], order='log_date', context=context)
        self.send_log(cr, uid, log_ids, context=context)

    def _generate_image_file_name(self, cr, uid, obj, field, extension,
                                  context=None):
        if getattr(obj, field.name):
            return "%d%s" % (obj.id, extension)
        else:
            return ''
