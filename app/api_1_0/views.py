#!/usr/bin/env python

from __future__ import unicode_literals
from flask import current_app, request, jsonify
from . import api_1_0
from .errors import bad_request
from .authentication import auth

from .smstools import *

@api_1_0.route('/monitoring', methods=['GET'])
def monitoring_view():
    return jsonify({'monitoring': 'ok'})

@api_1_0.route('/sms/<kind>/', methods=['GET'])
@auth.login_required
def list_some_sms(kind):
    return list_some_sms(kind)

@api_1_0.route('/sms/<kind>/<message_id>', methods=['GET'])
@auth.login_required
def get_some_sms_view(kind, message_id):
    return get_some_sms(kind, message_id)

@api_1_0.route('/sms/<kind>/<message_id>', methods=['DELETE'])
@auth.login_required
def delete_sms_view(kind, message_id):
    return delete_some_sms(kind, message_id)

@api_1_0.route('/sms/outgoing', methods=['GET', 'POST'])
@auth.login_required
def outgoing_view():
    required_fields = ( 'mobiles', 'text' )

    if request.method == 'POST':
        request_object = request.json
    elif request.method == 'GET':
        request_object = {}
        mobiles = request.args.get('mobiles')
        text = request.args.get('text')
        if mobiles:
            request_object['mobiles'] = mobiles.replace(' ', '+').split(',')
        if text:
            request_object['text'] = text

    # Check input data
    if type(request_object) is not dict:
        return bad_request('Wrong JSON object')
    for required_field in required_fields:
        if required_field not in request_object:
            return bad_request('Missing required: {0}'.format(required_field))
    if type(request_object['mobiles']) is not list:
        return bad_request('mobiles is not array')
    if len(request_object['mobiles']) == 0:
        return bad_request('mobiles array is empty')

    try:
        unicode_str = unicode()
    except NameError:
        unicode_str = str()

    for mobile in request_object['mobiles']:
        if type(mobile) is not type(unicode_str):
            return bad_request('mobiles is not unicode')

    if type(request_object['text']) is not type(unicode_str):
        return bad_request('text is not unicode')

    queue = request_object.get('queue', current_app.config.get('DEFAULTQUEUE'))
    data = {
        'mobiles': request_object['mobiles'],
        'text': request_object['text'],
        'queue' : queue
    }

    result = send_sms(data)
    return jsonify(result)

@api_1_0.route('/quota', methods=['GET'])
@auth.login_required
def get_quota_view():
    if quota_enabled():
        quota_info = get_quota()
    else:
        return not_allowed("quota disabled")
    result = {'quota': quota_info[0], 'quota_max': quota_info[1], 'quota_billing_day': quota_info[2]}
    return jsonify(result)

@api_1_0.route('/quota', methods=['DELETE'])
@auth.login_required
def quota_reset_view():
    return reset_quota()
