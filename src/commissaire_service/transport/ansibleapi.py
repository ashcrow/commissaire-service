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
Ansible API transport.
"""

import logging

from pkg_resources import resource_filename
from time import sleep

from .ansible_wrapper import gather_facts, execute_playbook


class Transport:
    """
    Transport using Ansible.
    """

    def __init__(self, remote_user='root'):
        """
        Creates an instance of the Transport.
        """
        self.logger = logging.getLogger('transport')
        # initialize needed objects
        self.remote_user = remote_user

    def _get_ansible_args(self, key_file):
        """
        Returns a list of additional command-line arguments to pass to
        Ansible.

        :param key_file: Full path to the file holding the private SSH key.
        :type key_file: str
        :returns: A list of command-line arguments.
        :rtype: list
        """
        ssh_args = ('-o StrictHostKeyChecking=no '
                    '-o ControlMaster=auto '
                    '-o ControlPersist=60s')

        ansible_args = [
            '--connection', 'ssh',
            '--private-key', key_file,
            '--user', self.remote_user,
            '--forks', '1',
            '--ssh-common-args', ssh_args
        ]

        if self.remote_user != 'root':
            self.logger.debug('Using user {0} for ssh communication.'.format(
                self.remote_user))
            ansible_args.extend([
                '--become',
                '--become-user', 'root',
                '--become-method', 'sudo'])

        return ansible_args

    def _run(self, ips, key_file, play_file,
             expected_results=[0], play_vars={}, disable_reconnect=False):
        """
        Common code used for each run.

        :param ips: IP address(es) to check.
        :type ips: str or list
        :param key_file: Full path to the file holding the private SSH key.
        :type key_file: str
        :param play_file: Path to the ansible play file.
        :type play_file: str
        :param expected_results: List of expected return codes. Default: [0]
        :type expected_results: list
        :param disable_reconnect: Disables connection loop.
        :type disable_reconnect:  bool
        :returns: Ansible exit code
        :type: int
        """
        ansible_args = self._get_ansible_args(key_file)
        if play_vars:
            ansible_args.extend(['--extra-vars', json.dumps(play_vars)])

        self.logger.debug('Ansible arguments: {}'.format(ansible_args))

        # actually run it
        for attempt in range(0, 3):
            result = execute_playbook(play_file, ips, ansible_args)

            # Deal with unreachable hosts (result == 3) by retrying
            # up to 3 times, sleeping 5 seconds after each attempt.
            if disable_reconnect:
                self.logger.warn(
                    'Not attempting to reconnect to {0}'.format(ips))
                break
            elif result == 3 and attempt < 2:
                self.logger.warn(
                    'One or more hosts in {0} is unreachable, '
                    'retrying in 5 seconds...'.format(ips))
                sleep(5)
            else:
                break

        if result in expected_results:
            self.logger.debug('{0}: Good result {1}'.format(ip, result))
            return result

        self.logger.debug('{0}: Bad result {1}'.format(ip, result))
        raise Exception('Can not run for {0}'.format(ip))

    def deploy(self, ips, key_file, oscmd, kwargs):
        """
        Deploys a tree image on a host via ansible.

        :param ips: IP address(es) to upgrade.
        :type ips: str or list
        :param key_file: Full path to the file holding the private SSH key.
        :type key_file: str
        :param oscmd: OSCmd class to use
        :type oscmd: commissaire_service.oscmd.OSCmdBase
        :param kwargs: keyword arguments for the remote command
        :type kwargs: dict
        :returns: An Ansible status code (0=Success)
        :rtype: int
        """
        play_file = resource_filename(
            'commissaire', 'data/ansible/playbooks/deploy.yaml')
        deploy_command = " ".join(oscmd.deploy(kwargs['version']))
        return self._run(
            ips, key_file, play_file, [0],
            {'commissaire_deploy_command': deploy_command})

    def upgrade(self, ips, key_file, oscmd, kwargs):
        """
        Upgrades a host via ansible.

        :param ips: IP address(es) to upgrade.
        :type ips: str or list
        :param key_file: Full path to the file holding the private SSH key.
        :type key_file: str
        :param oscmd: OSCmd class to use
        :type oscmd: commissaire_service.oscmd.OSCmdBase
        :param kwargs: keyword arguments for the remote command
        :type kwargs: dict
        :returns: An Ansible status code (0=Success)
        :rtype: int
        """
        play_file = resource_filename(
            'commissaire', 'data/ansible/playbooks/upgrade.yaml')
        upgrade_command = " ".join(oscmd.upgrade())
        return self._run(
            ips, key_file, play_file, [0],
            {'commissaire_upgrade_command': upgrade_command})

    def restart(self, ips, key_file, oscmd, kwargs):
        """
        Restarts a host via ansible.

        :param ips: IP address(es) to restart.
        :type ips: str or list
        :param key_file: Full path to the file holding the private SSH key.
        :type key_file: str
        :param oscmd: OSCmd class to use
        :type oscmd: commissaire_service.oscmd.OSCmdBase
        :param kwargs: keyword arguments for the remote command
        :type kwargs: dict
        :returns: An Ansible status code (0=Success)
        :rtype: int
        """
        play_file = resource_filename(
            'commissaire', 'data/ansible/playbooks/restart.yaml')
        restart_command = " ".join(oscmd.restart())
        return self._run(
            ips, key_file, play_file, [0, 2],
            {'commissaire_restart_command': restart_command},
            disable_reconnect=True)

    def get_info(self, ip, key_file):
        """
        Get's information from the host via ansible.

        :param ip: IP address to check.
        :type ip: str
        :param key_file: Full path to the file holding the private SSH key.
        :type key_file: str
        :returns: tuple -- (exitcode(int), facts(dict)).
        """
        play_file = resource_filename(
            'commissaire', 'data/ansible/playbooks/get_info.yaml')
        result = self._run(ip, key_file, play_file)
        ansible_facts = gather_facts(ip, self._get_ansible_args(key_file))
        self.logger.debug('Ansible facts: {0}'.format(ansible_facts))
        facts = {}
        facts['os'] = ansible_facts['ansible_distribution'].lower()
        facts['cpus'] = ansible_facts['ansible_processor_cores']
        facts['memory'] = ansible_facts['ansible_memory_mb']['real']['total']
        space = 0
        for x in ansible_facts['ansible_mounts']:
            space += x['size_total']
        facts['space'] = space

        self.logger.debug('Grabbed Facts: {0}'.format(facts))
        return (result, facts)

    def check_host_availability(self, host, key_file):
        """
        Checks if a host node is available.

        :param host: The host model to check.
        :type host: commissaire.models.Host
        :param key_file: The path to the ssh_priv_key.
        :type key_file: str
        :returns: An Ansible status code (0=Success)
        :rtype: int
        """
        play_file = resource_filename(
            'commissaire',
            'data/ansible/playbooks/check_host_availability.yaml')
        return self._run(
            host.address, key_file, play_file, [0, 3], disable_reconnect=True)

    def bootstrap(self, ip, key_file, oscmd, etcd_config, cluster, network):
        """
        Bootstraps a host via ansible.

        :param ip: IP address to bootstrap.
        :type ip: str
        :param key_file: Full path to the file holding the private SSH key.
        :type key_file: str
        :param oscmd: OSCmd class to use
        :type oscmd: commissaire_service.oscmd.OSCmdBase
        :param etcd_config: An EtcdStoreHandler configuration
        :type etcd_config: dict
        :param cluster: A cluster model for the host
        :type cluster: commissaire.models.Cluster
        :param network: A network model for the host's cluster
        :type network: commissaire.models.Network
        :returns: An Ansible status code (0=Success)
        :rtype: int
        """
        self.logger.debug('Using {0} as the oscmd class for {1}'.format(
            oscmd.os_type, ip))

        play_vars = {
            'commissaire_cluster_type': cluster.type,
            'commissaire_bootstrap_ip': ip,
            # TODO: Where do we get this?
            'commissaire_docker_registry_host': '127.0.0.1',
            # TODO: Where do we get this?
            'commissaire_docker_registry_port': 8080,
            # TODO: Where do we get this?
            'commissaire_flannel_key': '/atomic01/network',
            'commissaire_docker_config_local': resource_filename(
                'commissaire', 'data/templates/docker'),
            'commissaire_flanneld_config_local': resource_filename(
                'commissaire', 'data/templates/flanneld'),
            'commissaire_install_libselinux_python': " ".join(
                oscmd.install_libselinux_python()),
            'commissaire_docker_config': oscmd.docker_config,
            'commissaire_flanneld_config': oscmd.flanneld_config,
            'commissaire_install_flannel': " ".join(oscmd.install_flannel()),
            'commissaire_install_docker': " ".join(oscmd.install_docker()),
            'commissaire_flannel_service': oscmd.flannel_service,
            'commissaire_docker_service': oscmd.flannel_service
        }

        # If we are a flannel_server network then set the var
        if network.type == 'flannel_server':
            play_vars['commissaire_flanneld_server'] = network.options.get(
                'address')
        elif network.type == 'flannel_etcd':
            play_vars['commissaire_etcd_server_url'] = etcd_config[
                'server_url']

        # Provide the CA if etcd is being used over https
        if (
                etcd_config['server_url'].startswith('https:') and
                'certificate_ca_path' in etcd_config):
            play_vars['commissaire_etcd_ca_path'] = oscmd.etcd_ca
            play_vars['commissaire_etcd_ca_path_local'] = (
                etcd_config['certificate_ca_path'])

        # Client Certificate additions
        if 'certificate_path' in etcd_config:
            self.logger.info('Using etcd client certs')
            play_vars['commissaire_etcd_client_cert_path'] = (
                oscmd.etcd_client_cert)
            play_vars['commissaire_etcd_client_cert_path_local'] = (
                etcd_config['certificate_path'])
            play_vars['commissaire_etcd_client_key_path'] = (
                oscmd.etcd_client_key)
            play_vars['commissaire_etcd_client_key_path_local'] = (
                etcd_config['certificate_key_path'])

        # XXX: Need to enable some package repositories for OS 'rhel'
        #      (or 'redhat').  This is a hack for a single corner case.
        #      We discussed how to generalize future cases where we need
        #      extra commands for a specific OS but decided to defer until
        #      more crop up.
        #
        #      See https://github.com/projectatomic/commissaire/pull/56
        #
        if oscmd.os_type in ('rhel', 'redhat'):
            play_vars['commissaire_enable_pkg_repos'] = (
                'subscription-manager repos '
                '--enable=rhel-7-server-extras-rpms '
                '--enable=rhel-7-server-optional-rpms')
        else:
            play_vars['commissaire_enable_pkg_repos'] = 'true'

        self.logger.debug('Variables for bootstrap: {0}'.format(play_vars))

        play_file = resource_filename(
            'commissaire', 'data/ansible/playbooks/bootstrap.yaml')

        return self._run(ip, key_file, play_file, [0], play_vars)
