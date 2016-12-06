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

import logging


class ContainerHandlerManager(object):
    """
    Configures ContainerHandler instances and routes storage requests to
    the appropriate handler.
    """

    def __init__(self):
        """
        Creates a new ContainerHandlerManager instance.
        """
        self._handlers = {}
        self.logger = logging.getLogger('containermgr')
        self.logger.setLevel(logging.DEBUG)

    def register(self, handler_type, config):
        """
        Registers a ContainerHandler for use in remote calls.

        :param handler_type: A class derived from ContainerHandler
        :type handler_type: type
        :param config: Configuration parameters for the handler
        :type config: dict
        """
        handler_type.check_config(config)
        self._handlers[config['name']] = handler_type(config)
        self.logger.info('Registered container handler {}'.format(
            config['name']))
        self.logger.debug('{}: {}'.format(
            self._handlers[config['name']], config))

    @property
    def handlers(self):
        """
        Returns all configured container manager instances.

        :returns: dict of container managers
        :rtype: dict
        """
        return self._handlers
