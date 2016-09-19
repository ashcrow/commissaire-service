
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
Service base class.
"""
import json
import logging
import multiprocessing
import traceback

from time import sleep

from commissaire.bus import BusMixin

from kombu import Connection, Exchange, Producer, Queue
from kombu.mixins import ConsumerMixin


def run_service(service_class, kwargs):
    """
    Creates a service instance and executes it's run method.

    :param service_cls: The CommissaireService class to manager.
    :type service_cls: class
    :param kwargs: Other keyword arguments to pass to service initializer.
    :type kwargs: dict
    """
    service = service_class(**kwargs)
    service.run()


class ServiceManager:
    """
    Multiprocessed Service Manager.
    """
    def __init__(self, service_class, process_count, exchange_name,
                 connection_url, qkwargs, **kwargs):
        """
        Initializes a new ServiceManager instance.

        :param service_cls: The CommissaireService class to manager.
        :type service_cls: class
        :param process_count: The number of processes to run.
        :type process_count: int
        :param exchange_name: Name of the topic exchange.
        :type exchange_name: str
        :param connection_url: Kombu connection url.
        :type connection_url: str
        :param qkwargs: One or more dicts keyword arguments for queue creation
        :type qkwargs: list
        :param kwargs: Other keyword arguments to pass to service initializer.
        :type kwargs: dict
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug('Initializing {0}'.format(self.__class__.__name__))
        self.service_class = service_class
        self._process_count = process_count
        self.connection_url = connection_url
        self.exchange_name = exchange_name
        self.qkwargs = qkwargs
        self.kwargs = kwargs
        self._pool = multiprocessing.Pool(
            self._process_count, maxtasksperchild=1)
        self._asyncs = []

    def _start_process(self):
        """
        Starts a single process based on class attributes.
        """
        kwargs = self.kwargs.copy()
        kwargs.update({
            'exchange_name': self.exchange_name,
            'connection_url': self.connection_url,
            'qkwargs': self.qkwargs,
        })
        self.logger.debug('Starting a new {} process with {}'.format(
            self.service_class.__class__.__name__, kwargs))
        self._asyncs.append(
            self._pool.apply_async(
                run_service,
                args=[self.service_class], kwds={'kwargs': kwargs}))

    def run(self):
        """
        Runs the manager "forever".
        """
        for x in range(0, self._process_count):
            self._start_process()
        while True:
            for process_result in self._asyncs:
                if process_result.ready():
                    self.logger.warn(
                        'Process {} finished. Replacing it with a '
                        'new one..'.format(process_result))
                    idx = self._asyncs.index(process_result)
                    process_result = self._asyncs.pop(idx)
                    self._start_process()
            sleep(1)


class CommissaireService(ConsumerMixin, BusMixin):
    """
    An example prototype CommissaireService base class.
    """

    def __init__(self, exchange_name, connection_url, qkwargs):
        """
        Initializes a new Service instance.

        :param exchange_name: Name of the topic exchange.
        :type exchange_name: str
        :param connection_url: Kombu connection url.
        :type connection_url: str
        :param qkwargs: One or more dicts keyword arguments for queue creation
        :type qkwargs: list
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug('Initializing {0}'.format(self.__class__.__name__))
        self.connection = Connection(connection_url)
        self._channel = self.connection.channel()
        self._exchange = Exchange(
            exchange_name, type='topic').bind(self._channel)
        self._exchange.declare()

        # Set up queues
        self._queues = []
        for kwargs in qkwargs:
            queue = Queue(**kwargs)
            queue.exchange = self._exchange
            queue = queue.bind(self._channel)
            self._queues.append(queue)
            self.logger.debug(queue.as_dict())

        # Create producer for publishing on topics
        self.producer = Producer(self._channel, self._exchange)
        self.logger.debug('Initializing finished')

    def get_consumers(self, Consumer, channel):
        """
        Returns the a list of consumers to watch. Called by the parent Mixin.

        :param Consumer: Message consumer class.
        :type Consumer: kombu.Consumer
        :param channel: An opened channel.
        :type channel: kombu.transport.*.Channel
        :returns: A list of Consumer instances.
        :rtype: list
        """
        consumers = []
        self.logger.debug('Setting up consumers')
        for queue in self._queues:
            self.logger.debug('Will consume on {0}'.format(queue.name))
            consumers.append(
                Consumer(queue, callbacks=[self._wrap_on_message]))
        self.logger.debug('Consumers: {}'.format(consumers))
        return consumers

    def on_message(self, body, message):
        """
        Called when a non-jsonrpc message arrives.

        :param body: Body of the message.
        :type body: dict
        :param message: The message instance.
        :type message: kombu.message.Message
        """
        self.logger.error(
            'Dropping unknown message: payload="{}", properties="{}"'.format(
                body, message.properties))

    def _wrap_on_message(self, body, message):
        """
        Wraps on_message for jsonrpc routing and logging.

        :param body: Body of the message.
        :type body: dict or json string
        :param message: The message instance.
        :type message: kombu.message.Message
        """
        self.logger.debug('Received message "{}" {}'.format(
            message.delivery_tag, body))
        expected_method = message.delivery_info['routing_key'].rsplit(
            '.', 1)[1]

        # If we don't get a valid message we default to -1 for the id
        uid = -1
        result = None
        try:
            # If we don't have a dict then it should be a json string
            if isinstance(body, str):
                body = json.loads(body)

            # If we have a method and it matches the routing key treat it
            # as a jsonrpc call
            if (
                    isinstance(body, dict) and
                    'method' in body.keys() and
                    body.get('method') == expected_method):
                uid = body.get('id', '-1')
                method = getattr(self, 'on_{}'.format(body['method']))
                if type(body['params']) is dict:
                    result = method(message=message, **body['params'])
                else:
                    result = method(message, *body['params'])

                self.logger.debug('Result for "{}": "{}"'.format(
                    uid, result))
            # Otherwise send it to on_message
            else:
                self.on_message(body, message)
        except Exception as error:
            jsonrpc_error_code = -32600
            # If there is an attribute error then use the Method Not Found
            # code in the error response
            if type(error) is AttributeError:
                jsonrpc_error_code = -32601
            elif type(error) is json.decoder.JSONDecodeError:
                jsonrpc_error_code = -32700  # Parser error
            result = {
                'jsonrpc': '2.0',
                'id': uid,
                'error': {
                    'code': jsonrpc_error_code,
                    'message': str(error),
                    'data': {
                        'exception': str(type(error))
                    }
                }
            }
            self.logger.warn(
                'Exception raised during method call:\n{}'.format(
                    traceback.format_exc()))

        # Reply back if needed
        if message.properties.get('reply_to'):
            self.logger.debug('Responding to {0}'.format(
                message.properties['reply_to']))
            response_queue = self.connection.SimpleQueue(
                message.properties['reply_to'])
            response_queue.put({
                'result': json.dumps(result),
            })
            response_queue.close()

        message.ack()
        self.logger.debug('Message "{0}" {1} ackd'.format(
            message.delivery_tag,
            ('was' if message.acknowledged else 'was not')))

    def respond(self, queue_name, id, payload, **kwargs):
        """
        Sends a response to a simple queue. Responses are sent back to a
        request and never should be the owner of the queue.

        :param queue_name: The name of the queue to use.
        :type queue_name: str
        :param id: The unique request id
        :type id: str
        :param payload: The content of the message.
        :type payload: dict
        :param kwargs: Keyword arguments to pass to SimpleQueue
        :type kwargs: dict
        """
        self.logger.debug('Sending response for message id "{}"'.format(id))
        send_queue = self.connection.SimpleQueue(queue_name, **kwargs)
        jsonrpc_msg = {
            'jsonrpc': "2.0",
            'id': id,
            'result': payload,
        }
        self.logger.debug('jsonrpc msg: {}'.format(jsonrpc_msg))
        send_queue.put(jsonrpc_msg)
        self.logger.debug('Sent response for message id "{}"'.format(id))
        send_queue.close()

    def onconnection_revived(self):  # pragma: no cover
        """
        Called when a reconnection occurs.
        """
        self.logger.info('Connection (re)established')

    def on_consume_ready(
            self, connection, channel, consumers):  # pragma: no cover
        """
        Called when the service is ready to consume messages.

        :param connection: The current connection instance.
        :type connection: kombu.Connection
        :param channel: The current channel.
        :type channel: kombu.transport.*.Channel
        :param consumers: A list of consumers.
        :type consumers: list
        """
        self.logger.info('Ready to consume')
        if self.logger.level == logging.DEBUG:
            queue_names = []
            for consumer in consumers:
                queue_names += [x.name for x in consumer.queues]
            self.logger.debug(
                'Consuming via connection "{0}" and channel "{1}" on '
                'the following queues: "{2}"'.format(
                    connection.as_uri(), channel, '", "'.join(queue_names)))

    def on_consume_end(self, connection, channel):  # pragma: no cover
        """
        Called when the service stops consuming.

        :param connection: The current connection instance.
        :type connection: kombu.Connection
        :param channel: The current channel.
        :type channel: kombu.transport.*.Channel
        """
        self.logger.warn('Consuming has ended')
