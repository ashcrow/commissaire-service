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

import json

import commissaire.constants as C

from commissaire.models import Cluster, Host, HostCreds, Network
from commissaire.storage.client import StorageClient
from commissaire.util.config import ConfigurationError
from commissaire.util.date import formatted_dt
from commissaire.util.ssh import TemporarySSHKey

from commissaire_service.oscmd import get_oscmd
from commissaire_service.service import (
    CommissaireService, add_service_arguments)
from commissaire_service.transport import ansibleapi


class InvestigatorService(CommissaireService):
    """
    Investigates new hosts to retrieve and store facts.
    """

    #: Default configuration file
    _default_config_file = '/etc/commissaire/investigator.conf'

    def __init__(self, exchange_name, connection_url, config_file=None):
        """
        Creates a new InvestigatorService.  If config_file is omitted,
        it will try the default location (/etc/commissaire/investigator.conf).

        :param exchange_name: Name of the topic exchange
        :type exchange_name: str
        :param connection_url: Kombu connection URL
        :type connection_url: str
        :param config_file: Optional configuration file path
        :type config_file: str or None
        """
        queue_kwargs = [
            {'routing_key': 'jobs.investigate'}
        ]

        super().__init__(
            exchange_name,
            connection_url,
            queue_kwargs,
            config_file=config_file)

        self.storage = StorageClient(self)

    def _get_etcd_config(self):
        """
        Extracts etcd configuration from a registered store handler.
        If no matching handler is found, return defaults for required
        values.

        :returns: A dictionary of configuration values
        :rtype: dict
        """
        response = self.request('storage.list_store_handlers')
        for handler in response.get('result', []):
            if handler['handler_type'] == 'EtcdStoreHandler':
                return handler['config']

        raise ConfigurationError(
            'Configuration is missing an EtcdStoreHandler')

    def _get_cluster_and_network_models(self, cluster_data):
        """
        Creates cluster and network models from the given cluster data.

        :param cluster_data: Data for a cluster
        :type cluster_data: dict
        :returns: a Cluster and Network model
        :rtype: tuple
        """
        try:
            cluster = Cluster.new(**cluster_data)
            network = self.storage.get_network(cluster.network)
        except TypeError:
            cluster = None
            network = Network.new(**C.DEFAULT_CLUSTER_NETWORK_JSON)

        return cluster, network

    def on_investigate(self, message, address, cluster_data={}):
        """
        Initiates an investigation of the requested host.

        :param message: A message instance
        :type message: kombu.message.Message
        :param address: Host address to investigate
        :type address: str
        :param cluster_data: Optional data for the associated cluster
        :type cluster_data: dict
        """
        # Statuses follow:
        # http://commissaire.readthedocs.org/en/latest/enums.html#host-statuses

        self.logger.info('{} is now in investigating.'.format(address))
        self.logger.debug('Investigating: {}'.format(address))
        if cluster_data:
            self.logger.debug('Related cluster: {}'.format(cluster_data))

        host = self.storage.get_host(address)
        host_creds = self.storage.get(HostCreds.new(address=host.address))
        transport = ansibleapi.Transport(host.remote_user)

        key = TemporarySSHKey(host_creds, self.logger)
        try:
            key.create()
        except Exception as error:
            self.logger.warn(
                'Unable to continue for {} due to '
                '{}: {}. Returning...'.format(address, type(error), error))
            raise error

        try:
            facts = transport.get_info(address, key.path)
            # recreate the host instance with new data
            data = json.loads(host.to_json())
            data.update(facts)
            host = Host.new(**data)
            host.last_check = formatted_dt()
            host.status = C.HOST_STATUS_BOOTSTRAPPING
            self.logger.info('Facts for {} retrieved'.format(address))
            self.logger.debug('Data: {}'.format(host.to_json()))
        except Exception as error:
            self.logger.warn('Getting info failed for {}: {}'.format(
                address, str(error)))
            host.status = C.HOST_STATUS_FAILED
            key.remove()
            raise error
        finally:
            # Save the updated host model.
            self.storage.save(host)

        self.logger.info(
            'Finished and stored investigation data for {}'.format(address))
        self.logger.debug(
            'Finished investigation update for {}: {}'.format(
                address, host.to_json()))

        self.logger.info('{} is now in bootstrapping'.format(address))
        oscmd = get_oscmd(host.os)
        try:
            etcd_config = self._get_etcd_config()
            cluster, network = self._get_cluster_and_network_models(
                cluster_data)

            container_manager = None
            if cluster:
                if cluster.container_manager:
                    container_manager = cluster.container_manager
                    self.logger.info(
                        'Using cluster "{}" managed by "{}"'.format(
                            cluster.name, container_manager))
                else:
                    self.logger.info(
                        'Using unmanaged cluster "{}"'.format(cluster.name))

            self.logger.info(
                'Using network "{}" of type "{}"'.format(
                    network.name, network.type))
            transport.bootstrap(
                address, key.path, oscmd, etcd_config, network)
            host.status = C.HOST_STATUS_DISASSOCIATED
        except Exception as error:
            self.logger.warn(
                'Unable to start bootstraping for {}: {}'.format(
                    address, str(error)))
            host.status = C.HOST_STATUS_FAILED
            key.remove()
            raise error
        finally:
            # Save the updated host model.
            self.storage.save(host)

        # Register with container manager (if applicable).
        try:
            if container_manager:
                self.request(
                    'container.register_node',
                    container_manager, address)
                host.status = C.HOST_STATUS_ACTIVE
        except Exception as error:
            self.logger.warn(
                'Unable to register {} to container manager "{}": {}'.format(
                    address, container_manager, error.args[0]))
            key.remove()
            raise error
        finally:
            # Save the updated host model.
            self.storage.save(host)

        self.logger.info(
            'Finished bootstrapping for {}'.format(address))
        self.logger.debug('Finished bootstrapping for {}: {}'.format(
            address, host.to_json()))

        # XXX TEMPORARILY DISABLED
        # WATCHER_QUEUE.put_nowait((host, datetime.datetime.utcnow()))

        key.remove()

        return host.to_json()


def main():  # pragma: no cover
    """
    Main entry point.
    """
    import argparse

    parser = argparse.ArgumentParser()
    add_service_arguments(parser)

    args = parser.parse_args()

    try:
        service = InvestigatorService(
            exchange_name=args.bus_exchange,
            connection_url=args.bus_uri,
            config_file=args.config_file)
        service.run()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
