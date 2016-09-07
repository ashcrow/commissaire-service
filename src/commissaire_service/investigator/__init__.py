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

import datetime
import json

import commissaire.constants as C

from commissaire.models import Cluster, Host, Network
from commissaire.util.ssh import TemporarySSHKey
from commissaire.util.config import ConfigurationError

from commissaire_service.oscmd import get_oscmd
from commissaire_service.service import CommissaireService
from commissaire_service.transport import ansibleapi


class InvestigatorService(CommissaireService):
    """
    Investigates new hosts to retrieve and store facts.
    """

    def __init__(self, exchange_name, connection_url):
        """
        Creates a new InvestigatorService.

        :param exchange_name: Name of the topic exchange
        :type exchange_name: str
        :param connection_url: Kombu connection URL
        :type connection_url: str
        """
        queue_kwargs = [
            {'routing_key': 'jobs.investigate'}
        ]
        CommissaireService.__init__(
            self, exchange_name, connection_url, queue_kwargs)

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
            network = Network.new(name=cluster.network)
            params = {
                'model_type_name', network.__class__.__name__,
                'model_json_data', network.to_json()
            }
            response = self.request('storage.get', params=params)
            network = Network.new(response['result'])
        except TypeError:
            cluster = Cluster.new(type=C.CLUSTER_TYPE_HOST)
            network = Network.new(**C.DEFAULT_CLUSTER_NETWORK_JSON)

        return cluster, network

    def on_investigate(self, message, address, remote_user='root',
                       cluster_data={}):
        """
        Initiates an investigation of the requested host.

        :param message: A message instance
        :type message: kombu.message.Message
        :param address: Host address to investigate
        :type address: str
        :param remote_user: User name under which to conduct the host
                            investigation (defaults to 'root')
        :type remote_user: str
        :param cluster_data: Optional data for the associated cluster
        :type cluster_data: dict
        """
        # Statuses follow:
        # http://commissaire.readthedocs.org/en/latest/enums.html#host-statuses

        self.logger.info('{0} is now in investigating.'.format(address))
        self.logger.debug(
            'Investigation details: {0} / "{1}". Related cluster: {2}'.format(
                address, remote_user, cluster_data))

        transport = ansibleapi.Transport(remote_user)

        try:
            host = Host.new(address=address, remote_user=remote_user)
        except Exception as error:
            self.logger.warn(
                'Unable to continue for {0} due to '
                '{1}: {2}. Returning...'.format(address, type(error), error))
            raise error

        key = TemporarySSHKey(host, self.logger)
        try:
            key.create()
        except Exception as error:
            self.logger.warn(
                'Unable to continue for {0} due to '
                '{1}: {2}. Returning...'.format(address, type(error), error))
            raise error

        try:
            result, facts = transport.get_info(address, key.path)
            # recreate the host instance with new data
            data = json.loads(host.to_json(secure=True))
            data.update(facts)
            host = Host(**data)
            host.last_check = datetime.datetime.utcnow().isoformat()
            host.status = 'bootstrapping'
            self.logger.info('Facts for {0} retrieved'.format(address))
            self.logger.debug('Data: {0}'.format(host.to_json()))
        except Exception as error:
            self.logger.warn('Getting info failed for {0}: {1}'.format(
                address, str(error)))
            host.status = 'failed'
            key.remove()
            raise error

        self.logger.info(
            'Finished and stored investigation data for {0}'.format(address))
        self.logger.debug(
            'Finished investigation update for {0}: {1}'.format(
                address, host.to_json()))

        self.logger.info('{0} is now in bootstrapping'.format(address))
        oscmd = get_oscmd(host.os)
        try:
            etcd_config = self._get_etcd_config()
            cluster, network = self._get_cluster_and_network_models(
                cluster_data)
            result, facts = transport.bootstrap(
                address, key.path, oscmd, etcd_config, cluster, network)
            host.status = 'inactive'
        except Exception as error:
            self.logger.warn(
                'Unable to start bootstraping for {0}: {1}'.format(
                    address, str(error)))
            host.status = 'disassociated'
            key.remove()
            raise error

        # Verify association with relevant container managers
        params = {
            'cluster_type': cluster.type,
            'address': address
        }
        response = self.request('storage.node_registered', params=params)
        if response['result']:
            host.status = 'active'

        self.logger.info(
            'Finished bootstrapping for {0}'.format(address))
        self.logger.debug('Finished bootstrapping for {0}: {1}'.format(
            address, host.to_json()))

        # XXX TEMPORARILY DISABLED
        # WATCHER_QUEUE.put_nowait((host, datetime.datetime.utcnow()))

        key.remove()

        return host.to_json()


if __name__ == '__main__':
    try:
        service = InvestigatorService(
            exchange_name='commissaire',
            connection_url='redis://127.0.0.1:6379/')
        service.run()
    except KeyboardInterrupt:
        pass
