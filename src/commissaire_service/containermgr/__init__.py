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

import importlib

from commissaire.containermgr import ContainerManagerError
from commissaire.util.config import ConfigurationError, read_config_file

from commissaire_service.service import (
    CommissaireService, add_service_arguments)
from commissaire_service.containermgr.containerhandlermanager import (
    ContainerHandlerManager)


class ContainerManagerService(CommissaireService):
    """
    Provides access to Container Managers.
    """

    def __init__(self, exchange_name, connection_url, config_file=None):
        """
        Creates a new ContainerManagerService and sets up ContainerHandler
        instances according to the config_file.  If config_file is omitted,
        it will try the default location (/etc/commissaire/containermgr.conf).

        :param exchange_name: Name of the topic exchange
        :type exchange_name: str
        :param connection_url: Kombu connection URL
        :type connection_url: str
        :param config_file: Optional configuration file path
        :type config_file: str or None
        """
        queue_kwargs = [{
            'name': 'containermgr',
            'routing_key': 'container.*',
            'exclusive': False,
        }]
        super().__init__(exchange_name, connection_url, queue_kwargs)
        self._manager = ContainerHandlerManager()

        config_data = read_config_file(
            config_file, '/etc/commissaire/containermgr.conf')
        container_handlers = config_data.get('container_handlers', [])

        if len(container_handlers) == 0:
            self.logger.info('No ContainerManagerHandlers were provided.')
        for config in container_handlers:
            self.register(config)

    def register(self, config):
        """
        Registers a new container handler type after extracting and validating
        information required for registration from the configuration data.

        :param config: A configuration dictionary
        :type config: dict
        """
        if type(config) is not dict:
            raise ConfigurationError(
                'Store handler format must be a JSON object, got a '
                '{} instead: {}'.format(type(config).__name__, config))

        # Import the handler class.
        try:
            module_name = config.pop('handler')
        except KeyError as error:
            raise ConfigurationError(
                'Container handler configuration missing "{}" key: '
                '{}'.format(error, config))
        try:
            module = importlib.import_module(module_name)
            handler_type = getattr(module, 'ContainerHandler')
        except ImportError:
            raise ConfigurationError(
                'Invalid container handler module name: {}'.format(
                    module_name))

        self._manager.register(handler_type, config)

    def on_list_handlers(self, message):
        """
        Handler for the "container.list_handlers" routing key.

        Returns a list of registered container handlers as dictionaries.
        Each dictionary contains the following:

           'name'         : The name of the container handler
           'handler_type' : Type type of the container handler
           'config'       : Dictionary of configuration values

        :param message: A message instance
        :type message: kombu.message.Message
        """
        result = []
        for name, handler in self._manager.handlers.items():
            result.append({
                'name': name,
                'handler_type': handler.__class__.__name__,
            })
        return result

    def on_node_registered(self, message, container_handler_name, address):
        """
        Checks if a node is registered to a specific container manager.

        :param message: A message instance
        :type message: kombu.message.Message
        :param container_handler_name: Name of the ContainerHandler to use.
        :type container_handler_name: str
        :param address: Address of the node
        :type address: str
        :returns: Whether the node is registered
        :rtype: bool
        """
        return self._node_operation(
            container_handler_name, 'node_registered', address)

    def on_register_node(self, message, container_handler_name, address):
        """
        Registers a node to a container manager.

        :param message: A message instance
        :type message: kombu.message.Message
        :param container_handler_name: Name of the ContainerHandler to use.
        :type container_handler_name: str
        :param address: Address of the node
        :type address: str
        :returns: Whether the node is registered
        :rtype: bool
        """
        return self._node_operation(
            container_handler_name, 'register_node', address)

    def on_remove_node(self, message, container_handler_name, address):
        """
        Removes a node from a container manager.

        :param message: A message instance
        :type message: kombu.message.Message
        :param container_handler_name: Name of the ContainerHandler to use.
        :type container_handler_name: str
        :param address: Address of the node
        :type address: str
        :returns: Whether the node is registered
        :rtype: bool
        """
        return self._node_operation(
            container_handler_name, 'remove_node', address)

    def _node_operation(self, container_handler_name, method, address):
        """
        Common code for getting node information.

        :param container_handler_name: Name of the ContainerHandler to use.
        :type container_handler_name: str
        :param method: The containermgr method to call.
        :type method: str
        :param address: Address of the node
        :type address: str
        :returns: Whether the node is registered
        :rtype: bool
        """
        try:
            container_handler = self._manager.handlers[container_handler_name]
            result = getattr(container_handler, method).__call__(address)

            self.logger.info(
                '{} called for {} via the container manager {}'.format(
                    method, address, container_handler_name))
            self.logger.debug('Result: {}'.format(result))

            if bool(result):
                return result

        except ContainerManagerError as error:
            self.logger.info('{} raised ContainerManagerError: {}'.format(
                error))
        except KeyError:
            self.logger.error('ContainerHandler {} does not exist.'.format(
                container_handler_name))
        except Exception as error:
            self.logger.error(
                'Unexpected error while attempting {} for node "{}" with '
                'containermgr "{}". {}: {}'.format(
                    method, address, container_handler_name,
                    error.__class__.__name__, error))

        return False

    def on_get_node_status(self, message, container_handler_name, address):
        """
        Gets a nodes status from the container manager.

        :param message: A message instance
        :type message: kombu.message.Message
        :param container_handler_name: Name of the ContainerHandler to use.
        :type container_handler_name: str
        :param address: Address of the node
        :type address: str
        :returns: Status of the node according to the container manager.
        :rtype: dict
        """
        result = self._node_operation(
            container_handler_name, 'get_node_status', address)
        if result is False:
            error = 'No status available for node {}'.format(address)
            self.logger.error(result)
            raise Exception(error)
        return result


def main():  # pragma: no cover
    """
    Main entry point.
    """
    import argparse

    parser = argparse.ArgumentParser()
    add_service_arguments(parser)

    args = parser.parse_args()

    try:
        service = ContainerManagerService(
            exchange_name=args.bus_exchange,
            connection_url=args.bus_uri,
            config_file=args.config_file)
        service.run()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':  # pragma: no cover
    main()
