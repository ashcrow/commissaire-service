# Copyright (C) 2016-2017  Red Hat, Inc
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
import json

import commissaire.models as models

from commissaire import constants as C
from commissaire.storage import StoreHandlerBase
from commissaire.util.config import (ConfigurationError, import_plugin)

from commissaire_service.service import (
    CommissaireService, add_service_arguments)
from commissaire_service.storage.storehandlermanager import (
    StoreHandlerManager)


class StorageService(CommissaireService):
    """
    Provides access to data stores to other services.
    """

    #: Default configuration file
    _default_config_file = '/etc/commissaire/storage.conf'

    def __init__(self, exchange_name, connection_url, config_file=None):
        """
        Creates a new StorageService and sets up StoreHandler instances
        according to the config_file.  If config_file is omitted, it will
        try the default location (/etc/commissaire/storage.conf).

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

        super().__init__(
            exchange_name,
            connection_url,
            queue_kwargs,
            config_file=config_file)

        self._manager = StoreHandlerManager()

        # Collect all model types in commissaire.models.
        self._model_types = {k: v for k, v in models.__dict__.items()
                             if isinstance(v, type) and
                             issubclass(v, models.Model)}

        store_handlers = self._config_data.get('storage_handlers', [])

        # Configure store handlers from user data.
        if len(store_handlers) == 0:
            store_handlers = [
                C.DEFAULT_ETCD_STORE_HANDLER
            ]
        for config in store_handlers:
            self.register_store_handler(config)

    def register_store_handler(self, config):  # pragma: no cover (temporary)
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
            module_name = config.pop('type')
        except KeyError:
            raise ConfigurationError(
                'Store handler configuration missing "type" key: '
                '{}'.format(config))
        handler_type = import_plugin(
            module_name, 'commissaire.storage', StoreHandlerBase)

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

    def _build_model(self, model_type_name, model_json_data):
        """
        Builds a model instance from a type name and model data, which may
        either be a dictionary or a JSON-parsable string.

        :param model_type_name: Model type for the JSON data
        :type model_type_name: str
        :param model_json_data: JSON representation of a model
        :type model_json_data: dict or str
        :returns: a model instance
        :rtype: commissaire_service.storage.models.Model
        """
        if isinstance(model_json_data, str):
            model_json_data = json.loads(model_json_data)
            if not isinstance(model_json_data, dict):
                raise json.decoder.JSONDecodeError(
                    'Model data expected to be a JSON object')
        model_type = self._model_types[model_type_name]
        return model_type.new(**model_json_data)

    def on_save(self, message, model_type_name, model_json_data):
        """
        Handler for the "storage.save" routing key.

        Takes model data which may have omitted optional fields, applies
        default values as needed, and saves it to a store; then returns the
        full saved JSON data.

        The JSON data argument may also be a list of models of the same type,
        which returns a list of full models; equivalent to calling the method
        once for each list item, with fewer bus messages.

        :param message: A message instance
        :type message: kombu.message.Message
        :param model_type_name: Model type for the JSON data
        :type model_type_name: str
        :param model_json_data: JSON representation of one or more models
        :type model_json_data: dict, str, [dict, ...] or [str, ...]
        :returns: full dict representation of the model(s)
        :rtype: dict or [dict, ...]
        """
        if isinstance(model_json_data, list):
            # Build all models first so we catch invalid input before
            # touching permanent storage.
            models = [self._build_model(model_type_name, x)
                      for x in model_json_data]
            return [self._manager.save(x).to_dict() for x in models]
        else:
            model = self._build_model(model_type_name, model_json_data)
            return self._manager.save(model).to_dict()

    def on_get(self, message, model_type_name, model_json_data):
        """
        Handler for the "storage.get" routing key.

        Returns JSON data from a store.  The input model data need only
        have enough information to uniquely identify the model.

        The JSON data argument may also be a list of models of the same type,
        which returns a list of full models; equivalent to calling the method
        once for each list item, with fewer bus messages.

        :param message: A message instance
        :type message: kombu.message.Message
        :param model_type_name: Model type for the JSON data
        :type model_type_name: str
        :param model_json_data: JSON identification of one or more models
        :type model_json_data: dict, str, [dict, ...] or [str, ...]
        :returns: full dict representation of the model(s)
        :rtype: dict or [dict, ...]
        """
        if isinstance(model_json_data, list):
            # Build all models first so we catch invalid input before
            # touching permanent storage.
            models = [self._build_model(model_type_name, x)
                      for x in model_json_data]
            return [self._manager.get(x).to_dict() for x in models]
        else:
            model = self._build_model(model_type_name, model_json_data)
            return self._manager.get(model).to_dict()

    def on_delete(self, message, model_type_name, model_json_data):
        """
        Handler for the "storage.delete" routing key.

        Deletes JSON data from a store.  The input model data need only
        have enough information to uniquely identify the model.

        The JSON data argument may also be a list of models of the same type;
        equivalent to calling the method once for each list item, with fewer
        bus messages.

        :param message: A message instance
        :type message: kombu.message.Message
        :param model_type_name: Model type for the JSON data
        :type model_type_name: str
        :param model_json_data: JSON identification of one or more models
        :type model_json_data: dict, str, [dict, ...] or [str, ...]
        """
        if not isinstance(model_json_data, list):
            model_json_data = [model_json_data]
        # Build all models first so we catch invalid input before touching
        # permanent storage.
        models = [self._build_model(model_type_name, x)
                  for x in model_json_data]
        for model_instance in models:
            self._manager.delete(model_instance)

    def on_list(self, message, model_type_name):  # pragma: no cover (temporary) # noqa
        """
        Handler for the "storage.list" routing key.

        Lists available data for the given model type from a store.

        :param message: A message instance
        :type message: kombu.message.Message
        :param model_type_name: Model type for the JSON data
        :type model_type_name: str
        :returns: a list of model representations as dicts
        :rtype: list
        """
        model_type = self._model_types[model_type_name]
        model_list = self._manager.list(model_type.new())
        return [model_instance.to_dict() for model_instance in model_list]

    def on_list_store_handlers(self, message):  # pragma: no cover (temporary)
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
    add_service_arguments(parser)

    args = parser.parse_args()

    try:
        service = StorageService(
            exchange_name=args.bus_exchange,
            connection_url=args.bus_uri,
            config_file=args.config_file)
        service.run()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':  # pragma: no cover
    main()
