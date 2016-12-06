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
Tests for commissaire_service.service.containermgr.ContainerManagerService.
"""

from . import TestCase, mock

from commissaire_service.containermgr import ContainerManagerService
from commissaire.containermgr.kubernetes import ContainerHandler


class TestContainerManagerService(TestCase):
    """
    Tests for the ContainerManagerService class.
    """

    def setUp(self):
        """
        Called before each test case.
        """
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

        self.service_instance = ContainerManagerService(
            'commissaire',
            'redis://127.0.0.1:6379/'
        )

    def tearDown(self):
        """
        Called after each test case.
        """
        self._connection.stop()
        self._exchange.stop()
        self._producer.stop()

    def test_register(self):
        """
        Verify ContainerManagerService.register can properly register handlers.
        """
        name = 'test'
        self.service_instance.register({
                'name': name,
                'handler':'commissaire.containermgr.kubernetes',
                'server_url': 'https://127.0.0.1:8080/'
            })
        # There should be 1 handler of the imported ContainerHandler type
        self.assertEquals(1, len(self.service_instance._manager.handlers))
        self.assertIn(name, self.service_instance._manager.handlers)
        self.assertIsInstance(
            self.service_instance._manager.handlers[name],
            ContainerHandler)

    def test_on_list_handler_when_empty(self):
        """
        Verify ContainerManagerService.on_list_handlers returns an empty list by default.
        """
        message = mock.MagicMock(
            payload='',
            delivery_info={
                'routing_key': 'container.list_handlers'})

        result = self.service_instance.on_list_handlers(message)
        # There should be no handlers by default
        self.assertEquals([], result)

    def test_on_list_handler_with_handler(self):
        """
        Verify ContainerManagerService.on_list_handlers returns a handler when one has been registered.
        """
        self.service_instance._manager._handlers = {
            'test': ContainerHandler(config={
                'server_url':'https://127.0.0.1:8080/'})}

        message = mock.MagicMock(
            payload='',
            delivery_info={
                'routing_key': 'container.list_handlers'})

        result = self.service_instance.on_list_handlers(message)
        # There should be no handlers by default
        self.assertEquals([{
            'name': 'test', 'handler_type': 'KubeContainerManager'}], result)

    def test_on_node_registered(self):
        """
        Verify ContainerManagerService.on_node_registered returns proper data.
        """
        message = mock.MagicMock(
            payload='',
            delivery_info={
            'routing_key': 'container.node_registered'})

        for code, result in ((200, True), (404, False)):
            ch = mock.MagicMock()
            ch.node_registered.return_value = result
            self.service_instance._manager._handlers = {'test': ch}

            self.assertEquals(
                result,
                self.service_instance.on_node_registered(
                    message, 'test', '127.0.0.1'))

    def test_on_register_node_and_remove_node(self):
        """
        Verify on_register/remove_node responds properly.
        """
        for method in ('register_node', 'remove_node'):
            message = mock.MagicMock(
                payload='',
                delivery_info={
                    'routing_key': 'container.{}'.format(method)})

            for code, result in ((201, True), (404, False)):
                ch = mock.MagicMock()
                getattr(ch, method).return_value = result
                self.service_instance._manager._handlers = {'test': ch}

                self.assertEquals(
                    result,
                    getattr(self.service_instance, 'on_{}'.format(method))(
                        message, 'test', '127.0.01'))

    def test_on_register_node_and_remove_node_with_exceptions(self):
        """
        Verify on_register/remove_node handle exceptions.
        """
        for method in ('register_node', 'remove_node'):
            message = mock.MagicMock(
                payload='',
                delivery_info={
                    'routing_key': 'container.{}'.format(method)})

            for exc in (KeyError, Exception):
                # XXX: This isn't the exact place the exceptions would be
                # raised, but it is in the correct block
                ch = mock.MagicMock()
                getattr(ch, method).side_effect = exc
                self.service_instance._manager._handlers = {'test': ch}

                self.assertEquals(
                    False,
                    getattr(self.service_instance, 'on_{}'.format(method))(
                        message, 'test', '127.0.01'))

    def test_on_get_node_status(self):
        """
        Verify ContainerManagerService.get_node_status returns proper data on success.
        """
        message = mock.MagicMock(
            payload='',
            delivery_info={
            'routing_key': 'container.get_node_status'})

        expected = {'test': 'test'}
        ch = mock.MagicMock()
        ch.get_node_status.return_value = expected
        self.service_instance._manager._handlers = {'test': ch}

        self.assertEquals(
            expected,
            self.service_instance.on_get_node_status(
                message, 'test', '127.0.0.1'))

    def test_on_get_node_status_with_failure(self):
        """
        Verify ContainerManagerService.get_node_status returns proper data on failure.
        """
        message = mock.MagicMock(
            payload='',
            delivery_info={
            'routing_key': 'container.get_node_status'})

        ch = mock.MagicMock()
        ch.get_node_status.side_effect = Exception
        self.service_instance._manager._handlers = {'test': ch}

        self.assertRaises(
            Exception,
            self.service_instance.on_get_node_status,
            message, 'test', '127.0.0.1')
