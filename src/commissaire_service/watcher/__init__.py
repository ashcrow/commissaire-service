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
The host node watcher.
"""

import json

from datetime import datetime, timedelta
from time import sleep

from commissaire import constants as C
from commissaire.models import WatcherRecord
from commissaire.storage.client import StorageClient
from commissaire.util.config import read_config_file
from commissaire.util.date import formatted_dt
from commissaire.util.ssh import TemporarySSHKey

from commissaire_service.service import (
    CommissaireService, add_service_arguments)
from commissaire_service.transport import ansibleapi


class WatcherService(CommissaireService):
    """
    Periodically connects to hosts to check their status.
    """

    def __init__(self, exchange_name, connection_url, config_file=None):
        """
        Creates a new WatcherService.  If config_file is omitted,
        it will try the default location (/etc/commissaire/watcher.conf).

        :param exchange_name: Name of the topic exchange
        :type exchange_name: str
        :param connection_url: Kombu connection URL
        :type connection_url: str
        :param config_file: Optional configuration file path
        :type config_file: str or None
        """
        queue_kwargs = [{
            'name': 'watcher',
            'exclusive': False,
            'routing_key': 'jobs.watcher',
        }]
        # Store the last address seen for backoff
        self.last_address = None
        super().__init__(exchange_name, connection_url, queue_kwargs)
        self.storage = StorageClient(self)

        # Apply any logging configuration for this service.
        read_config_file(config_file, '/etc/commissaire/watcher.conf')

    def on_message(self, body, message):
        """
        Called when a non-jsonrpc message arrives.

        :param body: Body of the message.
        :type body: dict
        :param message: The message instance.
        :type message: kombu.message.Message
        """
        record = WatcherRecord(**json.loads(body))
        # Ack the message so it does not requeue on it's own
        message.ack()
        self.logger.debug(
            'Checking on WatcherQueue item: {}'.format(record.to_json()))
        if datetime.strptime(record.last_check, C.DATE_FORMAT) < (
                datetime.utcnow() - timedelta(minutes=1)):
            try:
                self._check(record.address)
            except Exception as error:
                self.logger.debug('Error: {}: {}'.format(type(error), error))
            record.last_check = formatted_dt()
        else:
            if self.last_address == record.address:
                # Since we got the same address we could process twice
                # back off a little extra
                self.logger.debug(
                    'Got "{}" twice. Backing off...'.format(record.address))
                sleep(10)
            else:
                # Since the top item wasn't ready for processing sleep a bit
                sleep(2)
        self.last_address = record.address
        # Requeue the host
        self.producer.publish(record.to_json(), 'jobs.watcher')

    def _check(self, address):
        """
        Initiates an check on the requested host.

        :param address: Host address to investigate
        :type address: str
        :param cluster_data: Optional data for the associated cluster
        :type cluster_data: dict
        """
        # Statuses follow:
        # http://commissaire.readthedocs.org/en/latest/enums.html#host-statuses

        self.logger.info('Checking host "{}".'.format(address))

        host = self.storage.get_host(address)
        transport = ansibleapi.Transport(host.remote_user)

        with TemporarySSHKey(host, self.logger) as key:
            try:
                self.logger.debug(
                    'Starting watcher run for host "{}"'.format(address))
                result = transport.check_host_availability(host, key.path)
                host.last_check = formatted_dt()
                self.logger.debug(
                    'Watcher result for host {}: {}'.format(address, result))
            except Exception as error:
                self.logger.warn(
                    'Failed to connect to host node "{}"'.format(address))
                self.logger.debug(
                    'Watcher failed for host node "{}" with {}: {}'.format(
                        address, str(error), error))
                host.status = 'failed'
                raise error
            finally:
                # Save the model
                self.storage.save(host)
            self.logger.info(
                'Finished watcher run for host "{}"'.format(address))


def main():  # pragma: no cover
    """
    Main entry point.
    """
    import argparse

    parser = argparse.ArgumentParser()
    add_service_arguments(parser)

    args = parser.parse_args()

    try:
        service = WatcherService(
            exchange_name=args.bus_exchange,
            connection_url=args.bus_uri,
            config_file=args.config_file)
        service.run()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
