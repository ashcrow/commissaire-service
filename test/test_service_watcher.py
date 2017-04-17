# Copyright (C) 2016  Red Hat, Inc
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Tests for commissaire_service.service.watcher module.
"""

import datetime

from . import TestCase, mock

from commissaire import models
from commissaire_service.watcher import WatcherService


class TestCommissaireService(TestCase):
    """
    Tests for the CommissaireService class.
    """

    def setUp(self):
        self._connection_patcher = mock.patch(
            'commissaire_service.service.Connection')
        self._exchange_patcher = mock.patch(
            'commissaire_service.service.Exchange')
        self._producer_patcher = mock.patch(
            'commissaire_service.service.Producer')
        self._connection = self._connection_patcher.start()
        self._exchange = self._exchange_patcher.start()
        self._producer = self._producer_patcher.start()

        self.queue_kwargs = [
            {'name': 'simple', 'routing_key': 'simple.*'},
        ]

        self.service_instance = WatcherService(
            'commissaire',
            'redis://127.0.0.1:6379/'
        )

    def tearDown(self):
        self._connection.stop()
        self._exchange.stop()
        self._producer.stop()

    def test_on_message_with_success(self):
        """
        Verify WatcherService.on_message handles a successful message properly.
        """
        body = models.WatcherRecord(
            address='127.0.0.1',
            last_check=(datetime.datetime.utcnow() - datetime.timedelta(
                    minutes=10)).isoformat())
        message = mock.MagicMock(
            payload=body.to_json(),
            delivery_info={'routing_key': 'jobs.watcher'})

        self.service_instance._check = mock.MagicMock()
        self.service_instance.on_message(body.to_json(), message)
        # The message must get ack'd
        message.ack.assert_called_once_with()
        # Check should be called
        self.service_instance._check.assert_called_once_with('127.0.0.1')

    def test_on_message_with_bad_connection(self):
        """
        Verify WatcherService.on_message handles bad connections properly.
        """
        body = models.WatcherRecord(
            address='127.0.0.1',
            last_check=(datetime.datetime.utcnow() - datetime.timedelta(
                    minutes=10)).isoformat())
        message = mock.MagicMock(
            payload=body.to_json(),
            delivery_info={'routing_key': 'jobs.watcher'})

        self.service_instance._check = mock.MagicMock(
            side_effect=Exception('test'))
        self.service_instance.on_message(body.to_json(), message)
        # The message must get ack'd
        message.ack.assert_called_once_with()
        # Check should be called
        self.service_instance._check.assert_called_once_with('127.0.0.1')

    def test_on_message_with_early_address(self):
        """
        Verify WatcherService.on_message requeues addresses that have been checked recently.
        """
        with mock.patch('commissaire_service.watcher.sleep') as _sleep:
            body = models.WatcherRecord(
                address='127.0.0.1',
                last_check=datetime.datetime.utcnow().isoformat())
            message = mock.MagicMock(
                payload=body.to_json(),
                delivery_info={'routing_key': 'jobs.watcher'})

            self.service_instance._check = mock.MagicMock()
            self.service_instance.on_message(body.to_json(), message)
            # The message must get ack'd
            message.ack.assert_called_once_with()
            # Check should NOT be called
            self.assertEquals(0, self.service_instance._check.call_count)
            # We should have been asked to sleep
            _sleep.assert_called_once_with(mock.ANY)

    def test__check_with_no_errors(self):
        """
        Verify _check works in a perfect scenario.
        """
        with mock.patch(
                'commissaire_service.transport.ansibleapi.Transport') as _transport:
            transport = _transport()

            self.service_instance.storage = mock.MagicMock()
            self.service_instance.storage.get_host.return_value = models.Host.new(
                address='127.0.0.1',
                last_check=datetime.datetime.min.isoformat())
            self.service_instance.storage.get.return_value = models.HostCreds.new(
                address='127.0.0.1')
            self.service_instance.storage.save.return_value = None
            self.service_instance._check('127.0.0.1')
            # The transport method should have been called once
            self.assertEquals(1, transport.check_host_availability.call_count)
            # Verify 'storage.save' got called
            self.service_instance.storage.save.assert_called_with(mock.ANY)
