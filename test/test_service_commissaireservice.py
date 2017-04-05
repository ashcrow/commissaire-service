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
Tests for commissaire_service.service.CommissaireService class.
"""

import uuid

from . import TestCase, mock
from commissaire_service.service import CommissaireService


ID = str(uuid.uuid4())


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

        self.service_instance = CommissaireService(
            'commissaire',
            'redis://127.0.0.1:6379/',
            self.queue_kwargs
        )

    def tearDown(self):
        self._connection.stop()
        self._exchange.stop()
        self._producer.stop()

    def test_initialization(self):
        """
        Verify CommissaireService initializes as expected.
        """
        # We should have one channel requested
        self.assertEquals(
            1, self.service_instance.connection.channel.call_count)
        # The exchange should be declared
        self.assertEquals(
            1, self.service_instance._exchange.declare.call_count)
        # We should have 1 queue ...
        self.assertEquals(
            1, len(self.service_instance._queues))
        # ... and it should match our queue_kwargs
        self.assertEquals(
            self.queue_kwargs[0]['name'],
            self.service_instance._queues[0].name)
        self.assertEquals(
            self.queue_kwargs[0]['routing_key'],
            self.service_instance._queues[0].routing_key)
        # We should have an associated Producer
        self._producer.assert_called_once_with(
            self.service_instance._channel, self.service_instance._exchange)

    def test_get_consumers(self):
        """
        Verify CommissaireService.get_consumers properly sets consumers.
        """
        Consumer = mock.MagicMock()
        channel = mock.MagicMock()

        consumers = self.service_instance.get_consumers(Consumer, channel)
        # The result should be a list
        self.assertIs(list, type(consumers))
        # With 1 Consumer in it
        self.assertEquals(1, len(consumers))
        # With 1 callback pointing to the message wrapper
        Consumer.assert_called_once_with(
            mock.ANY, callbacks=[self.service_instance.on_message])

    def test_on_message(self):
        """
        Verify CommissaireService.on_message handles bad messages.
        """
        message = mock.MagicMock(properties={'properties': 'here'})
        self.service_instance.on_message('test', message)

    def test_responds(self):
        """
        Verify CommissaireService.respond can respond to a request.
        """
        queue_name = 'test_queue'
        payload = {'test': 'data'}
        self.service_instance.respond(queue_name, ID, payload)
        # We should have had a SimpleQueue instance created
        self.service_instance.connection.SimpleQueue.assert_called_once_with(
            queue_name)
        # And there should be 1 call to put with a jsonrpc structure
        self.service_instance.connection.SimpleQueue.__call__(
            ).put.assert_called_once_with({
                'jsonrpc': "2.0",
                'id': ID,
                'result': payload,
            })
        # And finally the queue should be closed
        self.service_instance.connection.SimpleQueue.__call__(
            ).close.assert_called_once_with()

    def test_on_message_with_exposed_method(self):
        """
        Verify ServiceManager.on_message routes requests properly.
        """
        body = {
            'jsonrpc': '2.0',
            'id': ID,
            'method': 'method',
            'params': {'kwarg': 'value'},
        }
        message = mock.MagicMock(
            payload=body,
            properties={'reply_to': 'test_queue'},
            delivery_info={'routing_key': 'test.method'})
        self.service_instance.on_method = mock.MagicMock(return_value='{}')
        self.service_instance.on_message(body, message)
        # The on_method should have been called
        self.service_instance.on_method.assert_called_once_with(
            kwarg='value', message=message)

    def test_on_message_without_exposed_method(self):
        """
        Verify ServiceManager.on_message returns error if method doesn't exist.
        """
        body = {
            'jsonrpc': '2.0',
            'id': ID,
            'method': 'doesnotexist',
            'params': {'kwarg': 'value'},
        }
        message = mock.MagicMock(
            payload=body,
            properties={'reply_to': 'test_queue'},
            delivery_info={'routing_key': 'test.doesnotexist'})
        self.service_instance.on_message(body, message)
        self.service_instance.connection.SimpleQueue.assert_called_once_with(
            'test_queue')

    def test_on_message_with_bad_message(self):
        """
        Verify ServiceManager.on_message forwards to on_message on non jsonrpc messages.
        """
        self.service_instance.on_message =  mock.MagicMock()
        body = '[]'
        message = mock.MagicMock(
            payload=body,
            properties={'reply_to': 'test_queue'})
        self.service_instance.on_message(body, message)
        self.assertEquals(1, self.service_instance.on_message.call_count)
