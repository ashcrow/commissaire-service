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

import fnmatch
import importlib

import commissaire.models as models

from commissaire import constants as C
from commissaire.util.config import ConfigurationError, read_config_file

from commissaire_service.service import CommissaireService
from commissaire_service.storage.storehandlermanager import (
    StoreHandlerManager)


class StorageService(CommissaireService):
    """
    Provides access to data stores to other services.
    """

    def __init__(self, exchange_name, connection_url, config_file=None):
        """
        Creates a new StorageService and sets up StoreHandler instances
        according to the config_file.  If config_file is omitted, it will
        try the default location (/etc/commissaire/commissaire.conf).

        :param exchange_name: Name of the topic exchange
        :type exchange_name: str
        :param connection_url: Kombu connection URL
        :type connection_url: str
        :param config_file: Optional configuration file path
        :type config_file: str or None
        """
        queue_kwargs = [
            {'routing_key': 'storage.*'},
        ]
        CommissaireService.__init__(
            self, exchange_name, connection_url, queue_kwargs)

        self._manager = StoreHandlerManager()

        # Collect all model types in commissaire.models.
        self._model_types = {k: v for k, v in models.__dict__.items()
                             if isinstance(v, type) and
                             issubclass(v, models.Model)}

        config_data = read_config_file(config_file)
        store_handlers = config_data.get('storage-handlers', [])

        # Configure store handlers from user data.
        if len(store_handlers) == 0:
            store_handlers = [
                C.DEFAULT_ETCD_STORE_HANDLER
            ]
        for config in store_handlers:
            self.register_store_handler(config)

    def register_store_handler(self, config):
        """
        Registers a new store handler type after extracting and validating
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
            module_name = config.pop('name')
        except KeyError:
            raise ConfigurationError(
                'Store handler configuration missing "name" key: '
                '{}'.format(config))
        try:
            module = importlib.import_module(module_name)
            handler_type = getattr(module, 'StoreHandler')
        except ImportError:
            raise ConfigurationError(
                'Invalid store handler module name: {}'.format(module_name))

        # Match model types to type name patterns.
        matched_types = set()
        for pattern in config.pop('models', ['*']):
            matches = fnmatch.filter(self._model_types.keys(), pattern)
            if not matches:
                raise ConfigurationError(
                    'No match for model: {}'.format(pattern))
            matched_types.update([self._model_types[name] for name in matches])

        self._manager.register_store_handler(
            handler_type, config, *matched_types)

    def _build_model(self, model_type_name, model_kwargs):
        """
        Builds a model instance from a type name and kwargs.

        :param model_type_name: Model type for the JSON data
        :type model_type_name: str
        :param model_kwargs: Keyword args to pass to the model
        :type model_kwargs: dict
        :returns: a model instance
        :rtype: commissaire_service.storage.models.Model
        """
        model_type = self._model_types[model_type_name]
        return model_type.new(**model_kwargs)

    def on_save(self, message, model_type_name, model_json_data, secure=False):
        """
        Handler for the "storage.save" routing key.

        Takes model data which may have omitted optional fields, applies
        default values as needed, and saves it to a store; then returns the
        full saved JSON data.

        :param message: A message instance
        :type message: kombu.message.Message
        :param model_type_name: Model type for the JSON data
        :type model_type_name: str
        :param model_json_data: JSON representation of a model
        :type model_json_data: str
        :param secure: If the resulting dict should include secure content.
        :type secure: bool
        :returns: full dict representation of the model
        :rtype: dict
        """
        model_instance = self._build_model(model_type_name, model_json_data)
        saved_model_instance = self._manager.save(model_instance)
        return saved_model_instance.to_dict(secure=secure)

    def on_get(self, message, model_type_name, model_json_data, secure=False):
        """
        Handler for the "storage.get" routing key.

        Returns JSON data from a store.  The input model data need only
        have enough information to uniquely identify the model.

        :param message: A message instance
        :type message: kombu.message.Message
        :param model_type_name: Model type for the JSON data
        :type model_type_name: str
        :param model_json_data: JSON identification of a model
        :type model_json_data: str
        :param secure: If the resulting dict should include secure content.
        :type secure: bool
        :returns: full dict representation of the model
        :rtype: dict
        """
        model_instance = self._build_model(model_type_name, model_json_data)
        full_model_instance = self._manager.get(model_instance)
        return full_model_instance.to_dict(secure=secure)

    def on_delete(self, message, model_type_name, model_json_data):
        """
        Handler for the "storage.delete" routing key.

        Deletes JSON data from a store.  The input model data need only
        have enough information to uniquely identify the model.

        :param message: A message instance
        :type message: kombu.message.Message
        :param model_type_name: Model type for the JSON data
        :type model_type_name: str
        :param model_json_data: JSON identification of a model
        :type model_json_data: str
        """
        model_instance = self._build_model(model_type_name, model_json_data)
        self._manager.delete(model_instance)

    def on_list(self, message, model_type_name, secure=False):
        """
        Handler for the "storage.list" routing key.

        Lists available data for the given model type from a store.

        :param message: A message instance
        :type message: kombu.message.Message
        :param model_type_name: Model type for the JSON data
        :type model_type_name: str
        :param secure: If the results should include secure content.
        :type secure: bool
        :returns: a list of model representations as dicts
        :rtype: list
        """
        model_type = self._model_types[model_type_name]
        model_list = self._manager.list(model_type.new())
        return [model_instance.to_dict(secure=secure)
                for model_instance in model_list]

    def on_list_store_handlers(self, message):
        """
        Handler for the "storage.list_store_handlers" routing key.

        Returns a list of registered store handlers as dictionaries.
        Each dictionary contains the following:

           'handler_type' : Type name of the store handler
           'config'       : Dictionary of configuration values
           'model_types'  : List of model type names handled

        :param message: A message instance
        :type message: kombu.message.Message
        """
        result = []
        handlers = self._manager.list_store_handlers()
        for handler_type, config, model_types in handlers:
            model_types = [mt.__name__ for mt in model_types]
            model_types.sort()  # Just for readability
            result.append({
                'handler_type': handler_type.__name__,
                'config': config,
                'model_types': model_types
            })
        return result


def main():  # pragma: no cover
    """
    Main entry point.
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-c', '--config', type=str,
        help='Configuration file to use.')
    parser.add_argument(
        '--bus-exchange', type=str, default='commissaire',
        help='Message bus exchange name.')
    parser.add_argument(
        '--bus-uri', type=str, metavar='BUS_URI',
        default='redis://127.0.0.1:6379/',  # FIXME: Remove before release
        help=(
            'Message bus connection URI. See:'
            'http://kombu.readthedocs.io/en/latest/userguide/connections.html')
    )

    args = parser.parse_args()

    try:
        service = StorageService(
            exchange_name=args.bus_exchange,
            connection_url=args.bus_uri,
            config_file=args.config)
        service.run()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':  # pragma: no cover
    main()
