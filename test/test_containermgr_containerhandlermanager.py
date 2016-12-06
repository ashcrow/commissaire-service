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
Tests for commissaire_service.containermgr.ContainerHandlerManager class.
"""

import logging

from . import TestCase, mock
from commissaire.util.config import ConfigurationError
from commissaire.containermgr.kubernetes import KubeContainerManager
from commissaire_service.containermgr.containerhandlermanager import (
    ContainerHandlerManager)


class TestContainerHandlerManager(TestCase):
    """
    Tests for the ContainerHandlerManager class.
    """

    def setUp(self):
        """
        Set up before each test.
        """
        self.instance = ContainerHandlerManager()

    def test_initialization(self):
        """
        Verify ContainerHandlerManager initializes as expected.
        """
        self.assertEquals({}, self.instance.handlers)
        self.assertTrue(isinstance(self.instance.logger, logging.Logger))

    def test_register_with_valid_type(self):
        """
        Verify ContainerHandlerManager.register successfully registers ContainerHandlers.
        """
        self.instance.register(
            KubeContainerManager,
            config={'name': 'test', 'server_url': 'http://127.0.0.1:8080/'}
        )

    def test_register_with_invalid_type(self):
        """
        Verify ContainerHandlerManager.register fails with invalid types.
        """
        self.assertRaises(
            ConfigurationError,
            self.instance.register,
            KubeContainerManager, {})
