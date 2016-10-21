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

import json
import logging
import os.path  # Used for expanding paths
import subprocess

from ansible.errors import AnsibleParserError

# Set up our logging
logger = logging.getLogger('transport')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.formatter = logging.Formatter('%(name)s - %(message)s')
logger.addHandler(handler)


def get_inventory_file(hosts):  # pragma: no cover
    """
    Set up an --inventory-file option for the Ansible CLI.

    :param hosts: A host string or sequence of host strings.
    :type hosts: str, list, or tuple
    :returns: An argument list
    :rtype: list
    """
    # Ansible's parser likes trailing commas.
    if isinstance(hosts, str):
        hosts = hosts + ','
    elif hasattr(hosts, '__iter__'):
        hosts = ','.join(hosts) + ','
    else:
        raise AnsibleParserError(
            'Can not parse hosts of type {}'.format(type(hosts)))

    return ['--inventory-file', hosts]


def gather_facts(host, args=[]):  # pragma: no cover
    """
    Returns a dictionary of facts gathered by Ansible from a host.

    :param host: A host to gather facts from.
    :type host: str
    :param args: Other arguments to pass to the run.
    :type args: list
    :returns: A dictionary of facts
    :rtype: dict
    :raises subprocess.CalledProcessError: if Ansible returns a non-zero
                                           exit status
    """
    host = host.strip()
    cli_args = (['ansible', host, '--module-name', 'setup'] +
                get_inventory_file(host) + args)
    logger.info('Executing: {}'.format(' '.join(cli_args)))
    try:
        completed_process = subprocess.run(
            cli_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=True)
        # Output line is '$host | SUCCESS => { ... }'
        host_result, json_facts = completed_process.stdout.split(' => ', 1)
        return json.loads(json_facts).get('ansible_facts', {})
    except subprocess.CalledProcessError as error:
        logger.error('Ansible returned non-zero exit status {}'.format(
            error.returncode))
        logger.error('{}'.format(error.stderr))
        raise error


def execute_playbook(playbook, hosts, args=[]):  # pragma: no cover
    """
    Executes a playbook file for the given set of hosts, passing any
    additional command-line arguments to the playbook command.

    :param playbook: Full path to the playbook to execute.
    :type playbook: str
    :param hosts: A host or hosts to target the playbook against.
    :type hosts: str, list, or tuple
    :param args: Other arguments to pass to the run.
    :type args: list
    :raises subprocess.CalledProcessError: if Ansible returns a non-zero
                                           exit status
    """
    # Create the cli object
    cli_args = (['ansible-playbook'] + args +
                get_inventory_file(hosts) +
                [os.path.realpath(playbook)])
    logger.info('Executing: {}'.format(' '.join(cli_args)))
    try:
        completed_process = subprocess.run(
            cli_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=True)
        # TODO: Try to parse stdout?
        logger.debug('Playbook log:\n' + completed_process.stdout)
    except subprocess.CalledProcessError as error:
        logger.error('Ansible returned non-zero exit status {}'.format(
            error.returncode))
        logger.error('{}'.format(error.stderr))
        raise error
