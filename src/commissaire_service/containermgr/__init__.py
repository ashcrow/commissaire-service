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

from commissaire import models

from commissaire.bus import ContainerManagerError
from commissaire.containermgr import ContainerManagerBase
from commissaire.storage.client import StorageClient
from commissaire.util.config import import_plugin

from commissaire_service.service import (
    CommissaireService, add_service_arguments)


class ContainerManagerService(CommissaireService):
    """
    Provides access to Container Managers.
    """

    #: Default configuration file
    _default_config_file = '/etc/commissaire/containermgr.conf'

    def __init__(self, exchange_name, connection_url, config_file=None):
        """
        Creates a new ContainerManagerService.  If config_file is omitted,
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
        super().__init__(
            exchange_name,
            connection_url,
            queue_kwargs,
            config_file=config_file)

        self.storage = StorageClient(self)
        self.managers = {}

    def refresh_managers(self):
        """
        Fetches all ContainerManagerConfig records from the storage service,
        and instantiates the corresponding container manager plugins.

        This tries to reuse compatible container manager instances from
        previous calls to try and preserve any internal state.

        :raises ConfigurationError: on an invalid ContainerManagerConfig
        """
        current_managers = {}
        container = self.storage.list(models.ContainerManagerConfigs)
        for config in container.container_managers:
            # This will raise ConfigurationError if the import fails.
            manager_type = import_plugin(
                config.type, 'commissaire.containermgr', ContainerManagerBase)
            manager = self.managers.pop(config.name, None)
            if isinstance(manager, manager_type):
                # If there's already a compatible manager, reuse it.
                # XXX Manager instances may not keep their option
                #     dictionary so we can't detect option changes.
                current_managers[config.name] = manager
            else:
                current_managers[config.name] = manager_type(config.options)
        self.managers = current_managers

    def on_node_registered(self, message, container_manager_name, address):
        """
        Checks if a node is registered to a specific container manager.
        Raises ContainerManagerError if the node is NOT registered.

        :param message: A message instance
        :type message: kombu.message.Message
        :param container_manager_name: Name of the container manager to use.
        :type container_manager_name: str
        :param address: Address of the node
        :type address: str
        :raises: commissaire.bus.ContainerManagerError
        """
        self._node_operation(
            container_manager_name, 'node_registered', address)

    def on_register_node(self, message, container_manager_name, address):
        """
        Registers a node to a container manager.

        :param message: A message instance
        :type message: kombu.message.Message
        :param container_manager_name: Name of the container manager to use.
        :type container_manager_name: str
        :param address: Address of the node
        :type address: str
        :raises: commissaire.bus.ContainerManagerError
        """
        self._node_operation(
            container_manager_name, 'register_node', address)

    def on_remove_node(self, message, container_manager_name, address):
        """
        Removes a node from a container manager.

        :param message: A message instance
        :type message: kombu.message.Message
        :param container_manager_name: Name of the container manager to use.
        :type container_manager_name: str
        :param address: Address of the node
        :type address: str
        :raises: commissaire.bus.ContainerManagerError
        """
        self._node_operation(
            container_manager_name, 'remove_node', address)

    def on_remove_all_nodes(self, message, container_manager_name):
        """
        Removes all nodes from a container manager.

        :param message: A message instance
        :type message: kombu.message.Message
        :param container_manager_name: Name of the container manager to use.
        :type container_manager_name: str
        :raises: commissaire.bus.ContainerManagerError
        """
        self._node_operation(container_manager_name, 'remove_all_nodes')

    def _node_operation(self, container_manager_name, method, *args):
        """
        Common code for getting node information.

        :param container_manager_name: Name of the container manager to use.
        :type container_manager_name: str
        :param method: The containermgr method to call.
        :type method: str
        :param args: Additional arguments for the containermgr method.
        :type args: tuple
        :raises: commissaire.bus.ContainerManagerError
        """
        try:
            self.refresh_managers()
            container_manager = self.managers[container_manager_name]

            result = getattr(container_manager, method).__call__(*args)

            self.logger.info(
                '{}{} called via the container manager "{}"'.format(
                    method, args, container_manager_name))

            # Most operations lack a return statement.
            if result is not None:
                self.logger.debug('Result: {}'.format(result))
                return result

        except ContainerManagerError as error:
            self.logger.info('{} raised ContainerManagerError: {}'.format(
                container_manager_name, error))
            raise error
        except KeyError as error:
            self.logger.error('Container manager "{}" does not exist.'.format(
                container_manager_name))
            raise error
        except Exception as error:
            self.logger.error(
                'Unexpected error while attempting {}{} with '
                'container manager "{}". {}: {}'.format(
                    method, args, container_manager_name,
                    error.__class__.__name__, error))
            raise error

    def on_get_node_status(self, message, container_manager_name, address):
        """
        Gets a nodes status from the container manager.

        :param message: A message instance
        :type message: kombu.message.Message
        :param container_manager_name: Name of the container manager to use.
        :type container_manager_name: str
        :param address: Address of the node
        :type address: str
        :returns: Status of the node according to the container manager.
        :rtype: dict
        :raises: commissaire.bus.ContainerManagerError
        """
        return self._node_operation(
            container_manager_name, 'get_node_status', address)


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
