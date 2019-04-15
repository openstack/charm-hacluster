# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock
import os
import shutil
import sys
import tempfile
import unittest
import test_utils

mock_apt = mock.MagicMock()
sys.modules['apt_pkg'] = mock_apt
import hooks
import utils


@mock.patch.object(hooks, 'log', lambda *args, **kwargs: None)
@mock.patch('utils.COROSYNC_CONF', os.path.join(tempfile.mkdtemp(),
                                                'corosync.conf'))
class TestCorosyncConf(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tmpfile = tempfile.NamedTemporaryFile(delete=False)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        os.remove(self.tmpfile.name)

    @mock.patch.object(hooks, 'get_member_ready_nodes')
    @mock.patch.object(hooks, 'configure_resources_on_remotes')
    @mock.patch.object(hooks, 'configure_pacemaker_remote_stonith_resource')
    @mock.patch.object(hooks, 'configure_pacemaker_remote_resources')
    @mock.patch.object(hooks, 'set_cluster_symmetry')
    @mock.patch.object(hooks, 'write_maas_dns_address')
    @mock.patch('pcmk.wait_for_pcmk')
    @mock.patch('pcmk.crm_opt_exists')
    @mock.patch.object(hooks, 'is_leader')
    @mock.patch.object(hooks, 'configure_corosync')
    @mock.patch.object(hooks, 'configure_cluster_global')
    @mock.patch.object(hooks, 'configure_monitor_host')
    @mock.patch.object(hooks, 'configure_stonith')
    @mock.patch.object(hooks, 'related_units')
    @mock.patch.object(hooks, 'get_cluster_nodes')
    @mock.patch.object(hooks, 'relation_set')
    @mock.patch.object(hooks, 'relation_ids')
    @mock.patch.object(hooks, 'get_corosync_conf')
    @mock.patch('pcmk.commit')
    @mock.patch.object(hooks, 'config')
    @mock.patch.object(hooks, 'parse_data')
    def test_ha_relation_changed(self, parse_data, config, commit,
                                 get_corosync_conf, relation_ids, relation_set,
                                 get_cluster_nodes, related_units,
                                 configure_stonith, configure_monitor_host,
                                 configure_cluster_global, configure_corosync,
                                 is_leader, crm_opt_exists,
                                 wait_for_pcmk, write_maas_dns_address,
                                 set_cluster_symmetry,
                                 configure_pacemaker_remote_resources,
                                 configure_pacemaker_remote_stonith_resource,
                                 configure_resources_on_remotes,
                                 get_member_ready_nodes):

        def fake_crm_opt_exists(res_name):
            # res_ubuntu will take the "update resource" route
            return res_name == "res_ubuntu"

        crm_opt_exists.side_effect = fake_crm_opt_exists
        commit.return_value = 0
        is_leader.return_value = True
        related_units.return_value = ['ha/0', 'ha/1', 'ha/2']
        get_cluster_nodes.return_value = ['10.0.3.2', '10.0.3.3', '10.0.3.4']
        get_member_ready_nodes.return_value = ['10.0.3.2', '10.0.3.3',
                                               '10.0.3.4']
        relation_ids.return_value = ['hanode:1']
        get_corosync_conf.return_value = True
        cfg = {'debug': False,
               'prefer-ipv6': False,
               'corosync_transport': 'udpu',
               'corosync_mcastaddr': 'corosync_mcastaddr',
               'cluster_count': 3}

        config.side_effect = lambda key: cfg.get(key)

        rel_get_data = {'locations': {'loc_foo': 'bar rule inf: meh eq 1'},
                        'clones': {'cl_foo': 'res_foo meta interleave=true'},
                        'groups': {'grp_foo': 'res_foo'},
                        'colocations': {'co_foo': 'inf: grp_foo cl_foo'},
                        'resources': {'res_foo': 'ocf:heartbeat:IPaddr2',
                                      'res_bar': 'ocf:heartbear:IPv6addr',
                                      'res_ubuntu': 'IPaddr2'},
                        'resource_params': {'res_foo': 'params bar',
                                            'res_ubuntu': 'params ubuntu=42'},
                        'ms': {'ms_foo': 'res_foo meta notify=true'},
                        'orders': {'foo_after': 'inf: res_foo ms_foo'}}

        def fake_parse_data(relid, unit, key):
            return rel_get_data.get(key, {})

        parse_data.side_effect = fake_parse_data

        with mock.patch.object(tempfile, "NamedTemporaryFile",
                               side_effect=lambda: self.tmpfile):
            hooks.ha_relation_changed()

        relation_set.assert_any_call(relation_id='hanode:1', ready=True)
        configure_stonith.assert_called_with()
        configure_monitor_host.assert_called_with()
        configure_cluster_global.assert_called_with()
        configure_corosync.assert_called_with()
        set_cluster_symmetry.assert_called_with()
        configure_pacemaker_remote_resources.assert_called_with()
        write_maas_dns_address.assert_not_called()

        for kw, key in [('location', 'locations'),
                        ('clone', 'clones'),
                        ('group', 'groups'),
                        ('colocation', 'colocations'),
                        ('primitive', 'resources'),
                        ('ms', 'ms'),
                        ('order', 'orders')]:
            for name, params in rel_get_data[key].items():
                if name == "res_ubuntu":
                    commit.assert_any_call(
                        'crm configure load update %s' % self.tmpfile.name)

                elif name in rel_get_data['resource_params']:
                    res_params = rel_get_data['resource_params'][name]
                    commit.assert_any_call(
                        'crm -w -F configure %s %s %s %s' % (kw, name, params,
                                                             res_params))
                else:
                    commit.assert_any_call(
                        'crm -w -F configure %s %s %s' % (kw, name, params))

    @mock.patch.object(hooks, 'get_member_ready_nodes')
    @mock.patch.object(hooks, 'configure_resources_on_remotes')
    @mock.patch.object(hooks, 'configure_pacemaker_remote_stonith_resource')
    @mock.patch.object(hooks, 'configure_pacemaker_remote_resources')
    @mock.patch.object(hooks, 'set_cluster_symmetry')
    @mock.patch.object(hooks, 'write_maas_dns_address')
    @mock.patch.object(hooks, 'setup_maas_api')
    @mock.patch.object(hooks, 'validate_dns_ha')
    @mock.patch('pcmk.wait_for_pcmk')
    @mock.patch('pcmk.crm_opt_exists')
    @mock.patch.object(hooks, 'is_leader')
    @mock.patch.object(hooks, 'configure_corosync')
    @mock.patch.object(hooks, 'configure_cluster_global')
    @mock.patch.object(hooks, 'configure_monitor_host')
    @mock.patch.object(hooks, 'configure_stonith')
    @mock.patch.object(hooks, 'related_units')
    @mock.patch.object(hooks, 'get_cluster_nodes')
    @mock.patch.object(hooks, 'relation_set')
    @mock.patch.object(hooks, 'relation_ids')
    @mock.patch.object(hooks, 'get_corosync_conf')
    @mock.patch('pcmk.commit')
    @mock.patch.object(hooks, 'config')
    @mock.patch.object(hooks, 'parse_data')
    def test_ha_relation_changed_dns_ha(
            self, parse_data, config, commit, get_corosync_conf, relation_ids,
            relation_set, get_cluster_nodes, related_units, configure_stonith,
            configure_monitor_host, configure_cluster_global,
            configure_corosync, is_leader, crm_opt_exists, wait_for_pcmk,
            validate_dns_ha, setup_maas_api, write_maas_dns_addr,
            set_cluster_symmetry, configure_pacemaker_remote_resources,
            configure_pacemaker_remote_stonith_resource,
            configure_resources_on_remotes, get_member_ready_nodes):
        validate_dns_ha.return_value = True
        crm_opt_exists.return_value = False
        is_leader.return_value = True
        related_units.return_value = ['ha/0', 'ha/1', 'ha/2']
        get_cluster_nodes.return_value = ['10.0.3.2', '10.0.3.3', '10.0.3.4']
        get_member_ready_nodes.return_value = ['10.0.3.2', '10.0.3.3',
                                               '10.0.3.4']
        relation_ids.return_value = ['ha:1']
        get_corosync_conf.return_value = True
        cfg = {'debug': False,
               'prefer-ipv6': False,
               'corosync_transport': 'udpu',
               'corosync_mcastaddr': 'corosync_mcastaddr',
               'cluster_count': 3,
               'maas_url': 'http://maas/MAAAS/',
               'maas_credentials': 'secret'}

        config.side_effect = lambda key: cfg.get(key)

        rel_get_data = {'locations': {'loc_foo': 'bar rule inf: meh eq 1'},
                        'clones': {'cl_foo': 'res_foo meta interleave=true'},
                        'groups': {'grp_foo': 'res_foo'},
                        'colocations': {'co_foo': 'inf: grp_foo cl_foo'},
                        'resources': {'res_foo_hostname': 'ocf:maas:dns'},
                        'resource_params': {
                            'res_foo_hostname': 'params bar '
                                                'ip_address="172.16.0.1"'},
                        'ms': {'ms_foo': 'res_foo meta notify=true'},
                        'orders': {'foo_after': 'inf: res_foo ms_foo'}}

        def fake_parse_data(relid, unit, key):
            return rel_get_data.get(key, {})

        parse_data.side_effect = fake_parse_data

        hooks.ha_relation_changed()
        self.assertTrue(validate_dns_ha.called)
        self.assertTrue(setup_maas_api.called)
        write_maas_dns_addr.assert_called_with('res_foo_hostname',
                                               '172.16.0.1')
        # Validate maas_credentials and maas_url are added to params
        commit.assert_any_call(
            'crm -w -F configure primitive res_foo_hostname ocf:maas:dns '
            'params bar ip_address="172.16.0.1" maas_url="http://maas/MAAAS/" '
            'maas_credentials="secret"')

    @mock.patch.object(hooks, 'setup_maas_api')
    @mock.patch.object(hooks, 'validate_dns_ha')
    @mock.patch('pcmk.wait_for_pcmk')
    @mock.patch('pcmk.crm_opt_exists')
    @mock.patch.object(hooks, 'is_leader')
    @mock.patch.object(hooks, 'configure_corosync')
    @mock.patch.object(hooks, 'configure_cluster_global')
    @mock.patch.object(hooks, 'configure_monitor_host')
    @mock.patch.object(hooks, 'configure_stonith')
    @mock.patch.object(hooks, 'related_units')
    @mock.patch.object(hooks, 'get_cluster_nodes')
    @mock.patch.object(hooks, 'relation_set')
    @mock.patch.object(hooks, 'relation_ids')
    @mock.patch.object(hooks, 'get_corosync_conf')
    @mock.patch('pcmk.commit')
    @mock.patch.object(hooks, 'config')
    @mock.patch.object(hooks, 'parse_data')
    def test_ha_relation_changed_dns_ha_missing(
            self, parse_data, config, commit, get_corosync_conf, relation_ids,
            relation_set, get_cluster_nodes, related_units, configure_stonith,
            configure_monitor_host, configure_cluster_global,
            configure_corosync, is_leader, crm_opt_exists,
            wait_for_pcmk, validate_dns_ha, setup_maas_api):

        def fake_validate():
            raise utils.MAASConfigIncomplete('DNS HA invalid config')

        validate_dns_ha.side_effect = fake_validate
        crm_opt_exists.return_value = False
        is_leader.return_value = True
        related_units.return_value = ['ha/0', 'ha/1', 'ha/2']
        get_cluster_nodes.return_value = ['10.0.3.2', '10.0.3.3', '10.0.3.4']
        relation_ids.return_value = ['ha:1']
        get_corosync_conf.return_value = True
        cfg = {'debug': False,
               'prefer-ipv6': False,
               'corosync_transport': 'udpu',
               'corosync_mcastaddr': 'corosync_mcastaddr',
               'cluster_count': 3,
               'maas_url': 'http://maas/MAAAS/',
               'maas_credentials': None}

        config.side_effect = lambda key: cfg.get(key)

        rel_get_data = {'locations': {'loc_foo': 'bar rule inf: meh eq 1'},
                        'clones': {'cl_foo': 'res_foo meta interleave=true'},
                        'groups': {'grp_foo': 'res_foo'},
                        'colocations': {'co_foo': 'inf: grp_foo cl_foo'},
                        'resources': {'res_foo_hostname': 'ocf:maas:dns'},
                        'resource_params': {'res_foo_hostname': 'params bar'},
                        'ms': {'ms_foo': 'res_foo meta notify=true'},
                        'orders': {'foo_after': 'inf: res_foo ms_foo'}}

        def fake_parse_data(relid, unit, key):
            return rel_get_data.get(key, {})

        parse_data.side_effect = fake_parse_data
        with mock.patch.object(hooks, 'status_set') as mock_status_set:
            hooks.ha_relation_changed()
            mock_status_set.assert_called_with('blocked',
                                               'DNS HA invalid config')


class TestHooks(test_utils.CharmTestCase):
    TO_PATCH = [
        'config',
        'enable_lsb_services'
    ]

    def setUp(self):
        super(TestHooks, self).setUp(hooks, self.TO_PATCH)
        self.config.side_effect = self.test_config.get

    @mock.patch.object(hooks, 'filter_installed_packages')
    @mock.patch.object(hooks, 'setup_ocf_files')
    @mock.patch.object(hooks, 'apt_install')
    @mock.patch.object(hooks, 'status_set')
    @mock.patch.object(hooks, 'lsb_release')
    def test_install_xenial(self, lsb_release, status_set, apt_install,
                            setup_ocf_files, filter_installed_packages):
        lsb_release.return_value = {
            'DISTRIB_CODENAME': 'xenial'}
        filter_installed_packages.side_effect = lambda x: x
        expected_pkgs = [
            'crmsh', 'corosync', 'pacemaker', 'python-netaddr', 'ipmitool',
            'libmonitoring-plugin-perl', 'python3-requests-oauthlib']
        hooks.install()
        status_set.assert_called_once_with(
            'maintenance',
            'Installing apt packages')
        filter_installed_packages.assert_called_once_with(expected_pkgs)
        apt_install.assert_called_once_with(expected_pkgs, fatal=True)
        setup_ocf_files.assert_called_once_with()

    @mock.patch.object(hooks, 'filter_installed_packages')
    @mock.patch.object(hooks, 'setup_ocf_files')
    @mock.patch.object(hooks, 'apt_install')
    @mock.patch.object(hooks, 'status_set')
    @mock.patch.object(hooks, 'lsb_release')
    def test_install_bionic(self, lsb_release, status_set, apt_install,
                            setup_ocf_files, filter_installed_packages):
        lsb_release.return_value = {
            'DISTRIB_CODENAME': 'bionic'}
        filter_installed_packages.side_effect = lambda x: x
        expected_pkgs = [
            'crmsh', 'corosync', 'pacemaker', 'python-netaddr', 'ipmitool',
            'libmonitoring-plugin-perl', 'python3-requests-oauthlib',
            'python3-libmaas']
        hooks.install()
        status_set.assert_called_once_with(
            'maintenance',
            'Installing apt packages')
        filter_installed_packages.assert_called_once_with(expected_pkgs)
        apt_install.assert_called_once_with(expected_pkgs, fatal=True)
        setup_ocf_files.assert_called_once_with()

    @mock.patch.object(hooks, 'configure_stonith')
    @mock.patch.object(hooks, 'relation_ids')
    @mock.patch.object(hooks, 'hanode_relation_joined')
    @mock.patch.object(hooks, 'maintenance_mode')
    @mock.patch.object(hooks, 'is_leader')
    @mock.patch.object(hooks, 'update_nrpe_config')
    @mock.patch('pcmk.commit')
    @mock.patch('pcmk.wait_for_pcmk')
    @mock.patch.object(hooks, 'configure_corosync')
    @mock.patch('os.mkdir')
    @mock.patch('utils.config')
    @mock.patch('utils.rsync')
    @mock.patch('utils.mkdir')
    def test_config_changed(self, mock_mkdir, mock_rsync, mock_config,
                            mock_os_mkdir, mock_configure_corosync,
                            mock_wait_for_pcmk, mock_pcmk_commit,
                            mock_update_nrpe_config, mock_is_leader,
                            mock_maintenance_mode,
                            mock_hanode_relation_joined,
                            mock_relation_ids,
                            mock_configure_stonith):

        mock_config.side_effect = self.test_config.get
        mock_relation_ids.return_value = ['hanode:1']
        mock_wait_for_pcmk.return_value = True
        mock_is_leader.return_value = True
        hooks.config_changed()
        mock_maintenance_mode.assert_not_called()
        mock_relation_ids.assert_called_with('hanode')
        mock_hanode_relation_joined.assert_called_once_with('hanode:1')

        # enable maintenance
        self.test_config.set_previous('maintenance-mode', False)
        self.test_config.set('maintenance-mode', True)
        hooks.config_changed()
        mock_maintenance_mode.assert_called_with(True)

        # disable maintenance
        self.test_config.set_previous('maintenance-mode', True)
        self.test_config.set('maintenance-mode', False)
        hooks.config_changed()
        mock_maintenance_mode.assert_called_with(False)
        mock_configure_stonith.assert_called_with()

    @mock.patch.object(hooks, 'needs_maas_dns_migration')
    @mock.patch.object(hooks, 'relation_ids')
    def test_migrate_maas_dns_no_migration(self, relation_ids,
                                           needs_maas_dns_migration):
        needs_maas_dns_migration.return_value = False
        hooks.migrate_maas_dns()
        relation_ids.assert_not_called()

    @mock.patch.object(hooks, 'needs_maas_dns_migration')
    @mock.patch.object(hooks, 'write_maas_dns_address')
    @mock.patch.object(hooks, 'relation_ids')
    @mock.patch.object(hooks, 'related_units')
    @mock.patch.object(hooks, 'parse_data')
    def test_migrate_maas_dns_(self, parse_data, related_units, relation_ids,
                               write_maas_dns_address,
                               needs_maas_dns_migration):
        needs_maas_dns_migration.return_value = True
        related_units.return_value = 'keystone/0'
        relation_ids.return_value = 'ha:4'

        def mock_parse_data(relid, unit, key):
            if key == 'resources':
                return {'res_keystone_public_hostname': 'ocf:maas:dns'}
            elif key == 'resource_params':
                return {'res_keystone_public_hostname':
                        'params fqdn="keystone.maas" ip_address="172.16.0.1"'}
            else:
                raise KeyError("unexpected key {}".format(key))

        parse_data.side_effect = mock_parse_data
        hooks.migrate_maas_dns()
        write_maas_dns_address.assert_called_with(
            "res_keystone_public_hostname", "172.16.0.1")

    @mock.patch.object(hooks, 'get_relation_ip')
    @mock.patch.object(hooks, 'relation_set')
    def test_hanode_relation_joined(self,
                                    mock_relation_set,
                                    mock_get_relation_ip):
        mock_get_relation_ip.return_value = '10.10.10.2'
        hooks.hanode_relation_joined('hanode:1')
        mock_get_relation_ip.assert_called_once_with('hanode')
        mock_relation_set.assert_called_once_with(
            relation_id='hanode:1',
            relation_settings={'private-address': '10.10.10.2'}
        )

    @mock.patch.object(hooks, 'get_pcmkr_key')
    @mock.patch.object(hooks, 'relation_ids')
    @mock.patch.object(hooks, 'relation_set')
    def test_send_auth_key(self, relation_set, relation_ids, get_pcmkr_key):
        relation_ids.return_value = ['relid1']
        get_pcmkr_key.return_value = 'pcmkrkey'
        hooks.send_auth_key()
        relation_set.assert_called_once_with(
            relation_id='relid1',
            **{'pacemaker-key': 'pcmkrkey'})
