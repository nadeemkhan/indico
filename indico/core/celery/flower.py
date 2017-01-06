# This file is part of Indico.
# Copyright (C) 2002 - 2017 European Organization for Nuclear Research (CERN).
#
# Indico is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 3 of the
# License, or (at your option) any later version.
#
# Indico is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Indico; if not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import, unicode_literals

import functools
import json
import os
from urllib import urlencode

from tornado.auth import OAuth2Mixin, AuthError, _auth_return_future
from tornado.httpclient import AsyncHTTPClient, HTTPClient, HTTPRequest
from tornado.options import options
from tornado.web import asynchronous, HTTPError

from flower.views import BaseHandler
from flower.urls import settings


class FlowerAuthHandler(BaseHandler, OAuth2Mixin):
    _OAUTH_NO_CALLBACKS = False

    @property
    def _OAUTH_AUTHORIZE_URL(self):
        return os.environ['INDICO_FLOWER_AUTHORIZE_URL']

    @property
    def _OAUTH_ACCESS_TOKEN_URL(self):
        return os.environ['INDICO_FLOWER_TOKEN_URL']

    @_auth_return_future
    def get_authenticated_user(self, redirect_uri, code, callback):
        http = self.get_auth_http_client()
        body = urlencode({
            'redirect_uri': redirect_uri,
            'code': code,
            'client_id': os.environ['INDICO_FLOWER_CLIENT_ID'],
            'client_secret': os.environ['INDICO_FLOWER_CLIENT_SECRET'],
            'grant_type': 'authorization_code',
        })
        http.fetch(self._OAUTH_ACCESS_TOKEN_URL,
                   functools.partial(self._on_access_token, callback),
                   method='POST',
                   headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'},
                   body=body,
                   validate_cert=False)

    @asynchronous
    def _on_access_token(self, future, response):
        if response.error:
            future.set_exception(AuthError('OAuth authentication error: {}'.format(response)))
            return
        future.set_result(json.loads(response.body))

    def get_auth_http_client(self):
        return AsyncHTTPClient()

    @asynchronous
    def get(self):
        redirect_uri = 'http{}://{}:{}/login'.format('s' if 'ssl_options' in settings else '',
                                                     options.address or 'localhost',
                                                     options.port)
        if self.get_argument('code', False):
            self.get_authenticated_user(
                redirect_uri=redirect_uri,
                code=self.get_argument('code'),
                callback=self._on_auth,
            )
        else:
            self.authorize_redirect(
                redirect_uri=redirect_uri,
                client_id=os.environ['INDICO_FLOWER_CLIENT_ID'],
                scope=['read:user'],
                response_type='code',
                extra_params={'approval_prompt': 'auto'}
            )

    @asynchronous
    def _on_auth(self, user):
        if not user:
            raise HTTPError(500, 'OAuth authentication failed')
        access_token = user['access_token']
        req = HTTPRequest(os.environ['INDICO_FLOWER_USER_URL'],
                          headers={'Authorization': 'Bearer ' + access_token, 'User-agent': 'Tornado auth'},
                          validate_cert=False)
        response = HTTPClient().fetch(req)
        payload = json.loads(response.body.decode('utf-8'))
        if not payload or not payload['admin']:
            raise HTTPError(403, 'Access denied')
        self.set_secure_cookie('user', 'Indico Admin')
        self.redirect(self.get_argument('next', '/'))