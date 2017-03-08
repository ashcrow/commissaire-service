# Copyright (C) 2017  Red Hat, Inc
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
Test for commissaire_service.service.add_service_arguments function.
"""

import argparse

from . import TestCase
from commissaire_service.service import add_service_arguments


class Test_add_service_arguments(TestCase):
    """
    Test for the add_service_arguments helper function.
    """

    def test_add_service_arguments(self):
        """
        Verify arguments and defaults common to all services.
        """
        parser = argparse.ArgumentParser()
        add_service_arguments(parser)
        args = parser.parse_args(args=[])

        # Check for common arguments.
        self.assertEqual(len(vars(args)), 3)
        self.assertTrue(hasattr(args, 'config_file'))
        self.assertTrue(hasattr(args, 'bus_exchange'))
        self.assertTrue(hasattr(args, 'bus_uri'))

        # Check for presence of defaults.
        self.assertIsNone(args.config_file)
        self.assertIsNone(args.bus_uri)
        self.assertIsNotNone(args.bus_exchange)
