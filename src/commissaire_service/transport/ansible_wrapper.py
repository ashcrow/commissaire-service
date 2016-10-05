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

# This is Steve Milner's programmatic Ansible hack (the good kind) from:
# https://stevemilner.org/2016/07/30/programmatic-ansible-middle-ground/

# MONKEY PATCH to catch output. This must happen at the start of the code!
import logging

from ansible.utils.display import Display

# Set up our logging
logger = logging.getLogger('transport')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.formatter = logging.Formatter('%(name)s - %(message)s')
logger.addHandler(handler)

class LogForward(Display):
    """
    Quick hack of a log forwarder
    """

    def display(self, msg, screen_only=None, *args, **kwargs):
        """
        Pass display data to the logger.
        :param msg: The message to log.
        :type msg: str
        :param args: All other non-keyword arguments.
        :type args: list
        :param kwargs: All other keyword arguments.
        :type kwargs: dict
        """
        # Ignore if it is screen only output
        if screen_only:
            return
        logging.getLogger('transport').info(msg)

    # Forward it all to display
    info = display
    warning = display
    error = display
    # Ignore debug
    debug = lambda s, *a, **k: True

# By simply setting display Ansible will slurp it in as the display instance
display = LogForward()
# END MONKEY PATCH. Add code after this line.

import os  # Used for expanding paths

from ansible.cli.playbook import PlaybookCLI
from ansible.errors import AnsibleOptionsError, AnsibleParserError

def execute_playbook(playbook, hosts, args=[]):
    """
    :param playbook: Full path to the playbook to execute.
    :type playbook: str
    :param hosts: A host or hosts to target the playbook against.
    :type hosts: str, list, or tuple
    :param args: Other arguments to pass to the run.
    :type args: list
    :returns: An Ansible status code (0=Success)
    :rtype: int
    """
    # Set hosts args up right for the ansible parser. It likes to have trailing ,'s
    if isinstance(hosts, str):
        hosts = hosts + ','
    elif hasattr(hosts, '__iter__'):
        hosts = ','.join(hosts) + ','
    else:
        raise AnsibleParserError('Can not parse hosts of type {}'.format(
            type(hosts)))

    # Create the cli object
    cli_args = (['playbook'] + args +
                ['--inventory-file', hosts] +
                [os.path.realpath(playbook)])
    logger.info('Executing: {}'.format(' '.join(cli_args)))
    cli = PlaybookCLI(cli_args)
    # Parse args and run it
    try:
        cli.parse()
        # Return the result:
        # 0: Success
        # 1: "Error"
        # 2: Host failed
        # 3: Unreachable
        # 4: Parser Error
        # 5: Options error
        return cli.run()
    except (AnsibleParserError, AnsibleOptionsError) as error:
        logger.error('{}: {}'.format(type(error), error))
        raise error
