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
import re
import shutil
import subprocess
import tempfile
import unittest

import utils
import pcmk


def write_file(path, content, *args, **kwargs):
    with open(path, 'w') as f:
        f.write(content)
        f.flush()


@mock.patch.object(utils, 'log', lambda *args, **kwargs: None)
@mock.patch.object(utils, 'write_file', write_file)
class UtilsTestCaseWriteTmp(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        utils.COROSYNC_CONF = os.path.join(self.tmpdir, 'corosync.conf')

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    @mock.patch.object(utils, 'get_ha_nodes', lambda *args: {'1': '10.0.0.1'})
    @mock.patch.object(utils, 'relation_get')
    @mock.patch.object(utils, 'related_units')
    @mock.patch.object(utils, 'relation_ids')
    @mock.patch.object(utils, 'get_network_address')
    @mock.patch.object(utils, 'config')
    def check_debug(self, enabled, mock_config, get_network_address,
                    relation_ids, related_units, relation_get):
        cfg = {'debug': enabled,
               'prefer-ipv6': False,
               'corosync_mcastport': '1234',
               'corosync_transport': 'udpu',
               'corosync_mcastaddr': 'corosync_mcastaddr'}

        def c(k):
            return cfg.get(k)

        mock_config.side_effect = c
        get_network_address.return_value = "127.0.0.1"
        relation_ids.return_value = ['foo:1']
        related_units.return_value = ['unit-machine-0']
        relation_get.return_value = 'iface'

        conf = utils.get_corosync_conf()

        if enabled:
            self.assertEqual(conf['debug'], enabled)
        else:
            self.assertFalse('debug' in conf)

        self.assertTrue(utils.emit_corosync_conf())

        with open(utils.COROSYNC_CONF) as fd:
            content = fd.read()
            if enabled:
                pattern = 'debug: on\n'
            else:
                pattern = 'debug: off\n'

            matches = re.findall(pattern, content, re.M)
            self.assertEqual(len(matches), 2, str(matches))

    def test_debug_on(self):
        self.check_debug(True)

    def test_debug_off(self):
        self.check_debug(False)


class UtilsTestCase(unittest.TestCase):

    @mock.patch.object(utils, 'config')
    def test_get_transport(self, mock_config):
        mock_config.return_value = 'udp'
        self.assertEqual('udp', utils.get_transport())

        mock_config.return_value = 'udpu'
        self.assertEqual('udpu', utils.get_transport())

        mock_config.return_value = 'hafu'
        self.assertRaises(ValueError, utils.get_transport)

    def test_nulls(self):
        self.assertEquals(utils.nulls({'a': '', 'b': None, 'c': False}),
                          ['a', 'b'])

    @mock.patch.object(utils, 'local_unit', lambda *args: 'hanode/0')
    @mock.patch.object(utils, 'get_ipv6_addr')
    @mock.patch.object(utils, 'get_host_ip')
    @mock.patch.object(utils.utils, 'is_ipv6', lambda *args: None)
    @mock.patch.object(utils, 'get_corosync_id', lambda u: "%s-cid" % (u))
    @mock.patch.object(utils, 'peer_ips', lambda *args, **kwargs:
                       {'hanode/1': '10.0.0.2'})
    @mock.patch.object(utils, 'unit_get')
    @mock.patch.object(utils, 'config')
    def test_get_ha_nodes(self, mock_config, mock_unit_get, mock_get_host_ip,
                          mock_get_ipv6_addr):
        mock_get_host_ip.side_effect = lambda host: host

        def unit_get(key):
            return {'private-address': '10.0.0.1'}.get(key)

        mock_unit_get.side_effect = unit_get

        def config(key):
            return {'prefer-ipv6': False}.get(key)

        mock_config.side_effect = config
        nodes = utils.get_ha_nodes()
        self.assertEqual(nodes, {'hanode/0-cid': '10.0.0.1',
                                 'hanode/1-cid': '10.0.0.2'})

        self.assertTrue(mock_get_host_ip.called)
        self.assertFalse(mock_get_ipv6_addr.called)

    @mock.patch.object(utils, 'local_unit', lambda *args: 'hanode/0')
    @mock.patch.object(utils, 'get_ipv6_addr')
    @mock.patch.object(utils, 'get_host_ip')
    @mock.patch.object(utils.utils, 'is_ipv6')
    @mock.patch.object(utils, 'get_corosync_id', lambda u: "%s-cid" % (u))
    @mock.patch.object(utils, 'peer_ips', lambda *args, **kwargs:
                       {'hanode/1': '2001:db8:1::2'})
    @mock.patch.object(utils, 'unit_get')
    @mock.patch.object(utils, 'config')
    def test_get_ha_nodes_ipv6(self, mock_config, mock_unit_get, mock_is_ipv6,
                               mock_get_host_ip, mock_get_ipv6_addr):
        mock_get_ipv6_addr.return_value = '2001:db8:1::1'
        mock_get_host_ip.side_effect = lambda host: host

        def unit_get(key):
            return {'private-address': '10.0.0.1'}.get(key)

        mock_unit_get.side_effect = unit_get

        def config(key):
            return {'prefer-ipv6': True}.get(key)

        mock_config.side_effect = config
        nodes = utils.get_ha_nodes()
        self.assertEqual(nodes, {'hanode/0-cid': '2001:db8:1::1',
                                 'hanode/1-cid': '2001:db8:1::2'})

        self.assertFalse(mock_get_host_ip.called)
        self.assertTrue(mock_get_ipv6_addr.called)

    @mock.patch.object(utils, 'assert_charm_supports_dns_ha')
    @mock.patch.object(utils, 'config')
    def test_validate_dns_ha_valid(self, config,
                                   assert_charm_supports_dns_ha):
        cfg = {'maas_url': 'http://maas/MAAAS/',
               'maas_credentials': 'secret'}
        config.side_effect = lambda key: cfg.get(key)

        self.assertTrue(utils.validate_dns_ha())
        self.assertTrue(assert_charm_supports_dns_ha.called)

    @mock.patch.object(utils, 'assert_charm_supports_dns_ha')
    @mock.patch.object(utils, 'status_set')
    @mock.patch.object(utils, 'config')
    def test_validate_dns_ha_invalid(self, config, status_set,
                                     assert_charm_supports_dns_ha):
        cfg = {'maas_url': 'http://maas/MAAAS/',
               'maas_credentials': None}
        config.side_effect = lambda key: cfg.get(key)

        self.assertRaises(utils.MAASConfigIncomplete,
                          lambda: utils.validate_dns_ha())
        self.assertTrue(assert_charm_supports_dns_ha.called)

    @mock.patch.object(utils, 'apt_install')
    @mock.patch.object(utils, 'apt_update')
    @mock.patch.object(utils, 'add_source')
    @mock.patch.object(utils, 'config')
    def test_setup_maas_api(self, config, add_source, apt_update, apt_install):
        cfg = {'maas_source': 'ppa:maas/stable'}
        config.side_effect = lambda key: cfg.get(key)

        utils.setup_maas_api()
        add_source.assert_called_with(cfg['maas_source'])
        self.assertTrue(apt_install.called)

    @mock.patch('os.path.isfile')
    def test_ocf_file_exists(self, isfile_mock):
        RES_NAME = 'res_ceilometer_agent_central'
        resources = {RES_NAME: ('ocf:openstack:ceilometer-agent-central')}
        utils.ocf_file_exists(RES_NAME, resources)
        wish = '/usr/lib/ocf/resource.d/openstack/ceilometer-agent-central'
        isfile_mock.assert_called_once_with(wish)

    @mock.patch.object(subprocess, 'check_output')
    @mock.patch.object(subprocess, 'call')
    def test_kill_legacy_ocf_daemon_process(self, call_mock,
                                            check_output_mock):
        ps_output = '''
          PID CMD
          6863 sshd: ubuntu@pts/7
          11109 /usr/bin/python /usr/bin/ceilometer-agent-central --config
        '''
        check_output_mock.return_value = ps_output
        utils.kill_legacy_ocf_daemon_process('res_ceilometer_agent_central')
        call_mock.assert_called_once_with(['sudo', 'kill', '-9', '11109'])

    @mock.patch.object(pcmk, 'wait_for_pcmk')
    def test_try_pcmk_wait(self, mock_wait_for_pcmk):
        # Returns OK
        mock_wait_for_pcmk.side_effect = None
        self.assertEquals(None, utils.try_pcmk_wait())

        # Raises Exception
        mock_wait_for_pcmk.side_effect = pcmk.ServicesNotUp
        with self.assertRaises(pcmk.ServicesNotUp):
            utils.try_pcmk_wait()

    @mock.patch.object(pcmk, 'wait_for_pcmk')
    @mock.patch.object(utils, 'service_running')
    def test_services_running(self, mock_service_running,
                              mock_wait_for_pcmk):
        # OS not running
        mock_service_running.return_value = False
        self.assertFalse(utils.services_running())

        # Functional not running
        mock_service_running.return_value = True
        mock_wait_for_pcmk.side_effect = pcmk.ServicesNotUp
        with self.assertRaises(pcmk.ServicesNotUp):
            utils.services_running()

        # All running
        mock_service_running.return_value = True
        mock_wait_for_pcmk.side_effect = None
        mock_wait_for_pcmk.return_value = True
        self.assertTrue(utils.services_running())

    @mock.patch.object(pcmk, 'wait_for_pcmk')
    @mock.patch.object(utils, 'restart_corosync')
    def test_validated_restart_corosync(self, mock_restart_corosync,
                                        mock_wait_for_pcmk):
        # Services are down
        mock_restart_corosync.mock_calls = []
        mock_restart_corosync.return_value = False
        with self.assertRaises(pcmk.ServicesNotUp):
            utils.validated_restart_corosync(retries=3)
        self.assertEqual(3, len(mock_restart_corosync.mock_calls))

        # Services are up
        mock_restart_corosync.mock_calls = []
        mock_restart_corosync.return_value = True
        utils.validated_restart_corosync(retries=10)
        self.assertEqual(1, len(mock_restart_corosync.mock_calls))

    @mock.patch.object(utils, 'is_unit_paused_set')
    @mock.patch.object(utils, 'services_running')
    @mock.patch.object(utils, 'service_start')
    @mock.patch.object(utils, 'service_stop')
    @mock.patch.object(utils, 'service_running')
    def test_restart_corosync(self, mock_service_running,
                              mock_service_stop, mock_service_start,
                              mock_services_running, mock_is_unit_paused_set):
        # PM up, services down
        mock_service_running.return_value = True
        mock_is_unit_paused_set.return_value = False
        mock_services_running.return_value = False
        self.assertFalse(utils.restart_corosync())
        mock_service_stop.assert_has_calls([mock.call('pacemaker'),
                                            mock.call('corosync')])
        mock_service_start.assert_has_calls([mock.call('corosync'),
                                            mock.call('pacemaker')])

        # PM already down, services down
        mock_service_running.return_value = False
        mock_is_unit_paused_set.return_value = False
        mock_services_running.return_value = False
        self.assertFalse(utils.restart_corosync())
        mock_service_stop.assert_has_calls([mock.call('corosync')])
        mock_service_start.assert_has_calls([mock.call('corosync'),
                                            mock.call('pacemaker')])

        # PM already down, services up
        mock_service_running.return_value = True
        mock_is_unit_paused_set.return_value = False
        mock_services_running.return_value = True
        self.assertTrue(utils.restart_corosync())
        mock_service_stop.assert_has_calls([mock.call('pacemaker'),
                                            mock.call('corosync')])
        mock_service_start.assert_has_calls([mock.call('corosync'),
                                            mock.call('pacemaker')])

    @mock.patch.object(subprocess, 'check_call')
    @mock.patch.object(utils.os, 'mkdir')
    @mock.patch.object(utils.os.path, 'exists')
    @mock.patch.object(utils, 'render_template')
    @mock.patch.object(utils, 'write_file')
    @mock.patch.object(utils, 'is_unit_paused_set')
    @mock.patch.object(utils, 'config')
    def test_emit_systemd_overrides_file(self, mock_config,
                                         mock_is_unit_paused_set,
                                         mock_write_file, mock_render_template,
                                         mock_path_exists,
                                         mock_mkdir, mock_check_call):

        # Normal values
        cfg = {'service_stop_timeout': 30,
               'service_start_timeout': 90}
        mock_config.side_effect = lambda key: cfg.get(key)

        mock_is_unit_paused_set.return_value = True
        mock_path_exists.return_value = True
        utils.emit_systemd_overrides_file()
        self.assertEquals(2, len(mock_write_file.mock_calls))
        mock_render_template.assert_has_calls(
            [mock.call('systemd-overrides.conf', cfg),
             mock.call('systemd-overrides.conf', cfg)])
        mock_check_call.assert_has_calls([mock.call(['systemctl',
                                                     'daemon-reload'])])
        mock_write_file.mock_calls = []
        mock_render_template.mock_calls = []
        mock_check_call.mock_calls = []

        # Disable timeout
        cfg = {'service_stop_timeout': -1,
               'service_start_timeout': -1}
        expected_cfg = {'service_stop_timeout': 'infinity',
                        'service_start_timeout': 'infinity'}
        mock_config.side_effect = lambda key: cfg.get(key)
        mock_is_unit_paused_set.return_value = True
        mock_path_exists.return_value = True
        utils.emit_systemd_overrides_file()
        self.assertEquals(2, len(mock_write_file.mock_calls))
        mock_render_template.assert_has_calls(
            [mock.call('systemd-overrides.conf', expected_cfg),
             mock.call('systemd-overrides.conf', expected_cfg)])
        mock_check_call.assert_has_calls([mock.call(['systemctl',
                                                     'daemon-reload'])])

    @mock.patch('pcmk.set_property')
    @mock.patch('pcmk.get_property')
    def test_maintenance_mode(self, mock_get_property, mock_set_property):
        # enable maintenance-mode
        mock_get_property.return_value = 'false\n'
        utils.maintenance_mode(True)
        mock_get_property.assert_called_with('maintenance-mode')
        mock_set_property.assert_called_with('maintenance-mode', 'true')
        mock_get_property.reset_mock()
        mock_set_property.reset_mock()
        mock_get_property.return_value = 'true\n'
        utils.maintenance_mode(True)
        mock_get_property.assert_called_with('maintenance-mode')
        mock_set_property.assert_not_called()

        # disable maintenance-mode
        mock_get_property.return_value = 'true\n'
        utils.maintenance_mode(False)
        mock_get_property.assert_called_with('maintenance-mode')
        mock_set_property.assert_called_with('maintenance-mode', 'false')
        mock_get_property.reset_mock()
        mock_set_property.reset_mock()
        mock_get_property.return_value = 'false\n'
        utils.maintenance_mode(False)
        mock_get_property.assert_called_with('maintenance-mode')
        mock_set_property.assert_not_called()
