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
from commissaire.models import Host, WatcherRecord
from commissaire.util.ssh import TemporarySSHKey

from commissaire_service.service import CommissaireService
from commissaire_service.transport import ansibleapi


class WatcherService(CommissaireService):
    """
    Periodically connects to hosts to check their status.
    """

    def __init__(self, exchange_name, connection_url):
        """
        Creates a new WatcherService.

        :param exchange_name: Name of the topic exchange
        :type exchange_name: str
        :param connection_url: Kombu connection URL
        :type connection_url: str
        """
        queue_kwargs = [{
            'name': 'watcher',
            'exclusive': False,
            'routing_key': 'jobs.watcher',
        }]
        # Store the last address seen for backoff
        self.last_address = None
        super().__init__(exchange_name, connection_url, queue_kwargs)

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
            record.last_check = datetime.utcnow().isoformat()
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
        try:
            response = self.request('storage.get', params={
                'model_type_name': 'Host',
                'model_json_data': Host.new(address=address).to_json(),
                'secure': True,
            })
            host = Host.new(**response['result'])
        except Exception as error:
            self.logger.warn(
                'Unable to continue for host "{}" due to '
                '{}: {}. Returning...'.format(address, type(error), error))
            raise error

        transport = ansibleapi.Transport(host.remote_user)

        with TemporarySSHKey(host, self.logger) as key:
            try:
                self.logger.debug(
                    'Starting watcher run for host "{}"'.format(address))
                result = transport.check_host_availability(host, key.path)
                host.last_check = datetime.utcnow().isoformat()
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
                self.request('storage.save', params={
                    'model_type_name': host.__class__.__name__,
                    'model_json_data': host.to_json(),
                })
            self.logger.info(
                'Finished watcher run for host "{}"'.format(address))


def main():  # pragma: no cover
    """
    Main entry point.
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--bus-exchange', type=str, default='commissaire',
        help='Message bus exchange name.')
    parser.add_argument(
        '--bus-uri', type=str, metavar='BUS_URI',
        default='redis://127.0.0.1:6379/',  # FIXME Remove before release
        help=(
            'Message bus connection URI. See:'
            'http://kombu.readthedocs.io/en/latest/userguide/connections.html')
    )

    args = parser.parse_args()

    try:
        service = WatcherService(
            exchange_name=args.bus_exchange,
            connection_url=args.bus_uri)
        service.run()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
