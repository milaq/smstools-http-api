#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import os
import uuid
import time
import datetime
from email.message import Message
from flask import current_app, request, jsonify
from .authentication import auth
from .errors import not_found, forbidden, not_allowed, internal_error


def access_mobile(mobile):
    if not current_app.config['AUTH_ENABLED']:
        return True
    if not 'USER_WHITELIST' in current_app.config.keys():
        # Number access control disabled.
        return True
    if current_app.config['USER_WHITELIST'].get(auth.username()):
        return mobile in current_app.config['USER_WHITELIST'].get(auth.username(), [])
    else:
        return True

def validate_mobile(mobile):
    return re.match(r'^\+?\d+$', mobile) and True

def is_admin(user):
    if not current_app.config['AUTH_ENABLED']:
        return True
    if 'ADMIN_ACCOUNTS' in current_app.config and auth.username() in current_app.config['ADMIN_ACCOUNTS']:
        return True
    return False

def list_some_sms(kind):
    if kind not in current_app.config['KINDS']:
        return not_found(None)

    limit = current_app.config.get('LIMIT') or False
    message_ids = os.listdir(current_app.config[kind.upper()])
    message_ids = [mid for mid in message_ids if not mid.endswith('.LOCK')]
    total_count = len(message_ids)
    result = {}
    result['total_count'] = total_count
    result['limit'] = limit
    result['message_id'] = message_ids[:limit] if limit else message_ids

    return jsonify(result)

def delete_some_sms(kind, message_id):
    if kind not in current_app.config['KINDS']:
        return not_found(None)

    if is_admin(auth.username()):
        result = {}
        try:
            os.remove(current_app.config[kind.upper()] + "/" + message_id)
            result['deleted'] = kind + '/' + message_id
            return jsonify(result)
        except OSError:
            return not_found(None)

    return forbidden(None)

def get_some_sms(kind, message_id):
    if kind not in current_app.config['KINDS']:
        return not_found(None)
    try:
        with open(os.path.join(current_app.config[kind.upper()], message_id), "rb") as fp:
            header_flag = True
            result = {}

            for line in fp:
                line = line.decode('utf-8')
                if line == os.linesep:
                    header_flag = False
                if header_flag == True:
                    try:
                        key, val = line.split(':')
                        result[key] = val.strip()
                    except ValueError:
                        pass
                # text message
                if header_flag == False:
                    if result.get('Alphabet', '').startswith('UCS'):
                        charset = 'utf-16-be'
                    elif result.get('Alphabet', '').startswith('ISO'):
                        charset = 'latin'
                    else:
                        # Since UTF-8 is backwards compatible with US-ASCII and
                        # outgoing messages sent from the command line will be
                        # in UTF-8 without an Alphabet option, this will work.
                        charset = 'utf-8'
                    for line in fp:
                        result['text'] = result.get('text', '') + line.decode(charset)

            result['message_id'] = message_id

            if result['From'] == auth.username():
                return jsonify(result)
            elif is_admin(auth.username()):
                return jsonify(result)
            else:
                return forbidden(None)
    except EnvironmentError:
        return not_found(None)

def detect_coding(text):
    text_len=len(text)
    try:
        parts_count = text_len // 153 + (text_len % 153 > 0)
        text = text.encode('ascii')
        coding = 'ISO'
    except UnicodeEncodeError:
        parts_count = text_len // 67 + (text_len % 67 > 0)
        text = text.encode('utf-16-be')
        coding = 'UCS2'

    return text, coding, parts_count

def send_sms(data):
    text, coding, parts_count = detect_coding(data['text'])

    result = {
        'sent_text': data['text'],
        'parts_count': parts_count,
        'mobiles': {}
    }

    for mobile in data['mobiles']:
        # generate message_id
        message_id = str(uuid.uuid4())

        result['mobiles'][mobile] = {}
        result['mobiles'][mobile]['message_id'] = message_id
        result['mobiles'][mobile]['dlr_status'] = os.path.join(os.path.dirname(request.url),
                                                  os.path.basename(current_app.config['SENT']), message_id)

        if not validate_mobile(mobile):
            current_app.logger.error('Message from [%s] to [%s] have invalid mobile number' % (auth.username(), mobile))
            result['mobiles'][mobile]['response'] = 'Failed: invalid mobile number'
            continue

        if quota_enabled() and get_quota()[0] < parts_count:
            current_app.logger.error(
                'Message from [%s] to [%s] not sent. Message quota reached: %s' % (auth.username(), mobile, get_quota()))
            result['mobiles'][mobile]['response'] = 'Failed: message quota reached'
            continue

        if access_mobile(mobile):
            lock_file = os.path.join(current_app.config['OUTGOING'], message_id + '.LOCK')
            m = Message()
            m.add_header('From', auth.username())
            m.add_header('To', mobile)
            m.add_header('Alphabet', coding)
            if data.get('queue'):
                result.update({'queue' : data['queue']})
                m.add_header('Queue', result.get('queue'))
            m.set_payload(text)

            with open(lock_file, "wb") as fp:
                fp.write(m.as_bytes())

            msg_file = lock_file.split('.LOCK')[0]
            os.rename(lock_file, msg_file)
            os.chmod(msg_file, 0o660)
            current_app.logger.info('Message from [%s] to [%s] placed to the spooler as [%s]' % (auth.username(), mobile, msg_file))
            result['mobiles'][mobile]['response'] = 'Ok'

            if quota_enabled():
                write_quota(parts_count)
        else:
            current_app.logger.error('Message from [%s] to [%s] have forbidden mobile number' % (auth.username(), mobile))
            result['mobiles'][mobile]['response'] = 'Failed: forbidden mobile number'

    return result


def quota_enabled():
    if 'QUOTA_FILENAME' not in current_app.config \
            or 'QUOTA_MAX_SMS' not in current_app.config \
            or 'QUOTA_BILLING_DAY' not in current_app.config:
        return False
    return True


def write_quota(count=1):
    if not os.path.exists(current_app.config['QUOTA_FILENAME']):
        open(current_app.config['QUOTA_FILENAME'], 'w').close()
    with open(current_app.config['QUOTA_FILENAME'], "a") as f:
        for i in range(count):
            f.write(str(int(time.time())) + "\n")


def get_quota():
    quota_list = []
    try:
        with open(current_app.config['QUOTA_FILENAME'], "r") as f:
            for line in f:
                quota_list.append(line)
    except FileNotFoundError:
        quota_list = []
    quota_list = sorted(quota_list)
    current_date = datetime.datetime.utcnow()
    quota_day_date = datetime.datetime(current_date.year, current_date.month, int(current_app.config['QUOTA_BILLING_DAY']))
    quota_date_timestamp = time.mktime(quota_day_date.timetuple())
    try:
        quota_day_next = quota_day_date.replace(month=quota_day_date.month + 1)
    except ValueError:
        if quota_day_date.month == 12:
            quota_day_next = quota_day_date.replace(year=quota_day_date.year + 1, month=1)
        else:
            raise
    quota_delta = quota_day_next - current_date
    quota_count = 0
    for epoch in quota_list:
        if int(epoch) >= quota_date_timestamp:
            quota_count += 1
    return [int(current_app.config['QUOTA_MAX_SMS']) - quota_count, int(current_app.config['QUOTA_MAX_SMS']), quota_delta.days]

def reset_quota():
    if not is_admin(auth.username()):
        return forbidden(None)
    if not quota_enabled():
        return not_allowed("quota disabled")

    result = {}
    try:
        open(current_app.config['QUOTA_FILENAME'], 'w').close()
        return {"response": "quota cleared"}
    except OSError:
        return internal_error(None)
