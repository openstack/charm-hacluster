from __future__ import print_function

import mock
import os
import re
import shutil
import tempfile
import unittest

with mock.patch('charmhelpers.core.hookenv.config'):
    import hooks as hacluster_hooks


def local_log(msg, level='INFO'):
    print('[{}] {}'.format(level, msg))


def write_file(path, content, *args, **kwargs):
    with open(path, 'w') as f:
        f.write(content)
        f.flush()


class SwiftContextTestCase(unittest.TestCase):

    @mock.patch('hooks.config')
    def test_get_transport(self, mock_config):
        mock_config.return_value = 'udp'
        self.assertEqual('udp', hacluster_hooks.get_transport())

        mock_config.return_value = 'udpu'
        self.assertEqual('udpu', hacluster_hooks.get_transport())

        mock_config.return_value = 'hafu'
        self.assertRaises(ValueError, hacluster_hooks.get_transport)


@mock.patch('hooks.log', local_log)
@mock.patch('hooks.write_file', write_file)
class TestCorosyncConf(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        hacluster_hooks.COROSYNC_CONF = os.path.join(self.tmpdir,
                                                     'corosync.conf')

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_debug_on(self):
        self.check_debug(True)

    def test_debug_off(self):
        self.check_debug(False)

    @mock.patch('hooks.relation_get')
    @mock.patch('hooks.related_units')
    @mock.patch('hooks.relation_ids')
    @mock.patch('hacluster.get_network_address')
    @mock.patch('hooks.config')
    def check_debug(self, enabled, mock_config, get_network_address,
                    relation_ids, related_units, relation_get):
        cfg = {'debug': enabled,
               'prefer-ipv6': False,
               'corosync_transport': 'udpu',
               'corosync_mcastaddr': 'corosync_mcastaddr'}

        def c(k):
            return cfg.get(k)

        mock_config.side_effect = c
        get_network_address.return_value = "127.0.0.1"
        relation_ids.return_value = ['foo:1']
        related_units.return_value = ['unit-machine-0']
        relation_get.return_value = 'iface'

        hacluster_hooks.get_ha_nodes = mock.MagicMock()
        conf = hacluster_hooks.get_corosync_conf()
        self.assertEqual(conf['debug'], enabled)

        self.assertTrue(hacluster_hooks.emit_corosync_conf())

        with open(hacluster_hooks.COROSYNC_CONF) as fd:
            content = fd.read()
            if enabled:
                pattern = 'debug: on\n'
            else:
                pattern = 'debug: off\n'

            matches = re.findall(pattern, content, re.M)
            self.assertEqual(len(matches), 2, str(matches))

    @mock.patch('pcmk.wait_for_pcmk')
    @mock.patch('hooks.peer_units')
    @mock.patch('pcmk.crm_opt_exists')
    @mock.patch('hooks.oldest_peer')
    @mock.patch('hooks.configure_corosync')
    @mock.patch('hooks.configure_cluster_global')
    @mock.patch('hooks.configure_monitor_host')
    @mock.patch('hooks.configure_stonith')
    @mock.patch('hooks.related_units')
    @mock.patch('hooks.get_cluster_nodes')
    @mock.patch('hooks.relation_set')
    @mock.patch('hooks.relation_ids')
    @mock.patch('hooks.get_corosync_conf')
    @mock.patch('pcmk.commit')
    @mock.patch('hooks.config')
    @mock.patch('hooks.parse_data')
    def test_configure_principle_cluster_resources(self, parse_data, config,
                                                   commit,
                                                   get_corosync_conf,
                                                   relation_ids, relation_set,
                                                   get_cluster_nodes,
                                                   related_units,
                                                   configure_stonith,
                                                   configure_monitor_host,
                                                   configure_cluster_global,
                                                   configure_corosync,
                                                   oldest_peer, crm_opt_exists,
                                                   peer_units, wait_for_pcmk):
        crm_opt_exists.return_value = False
        oldest_peer.return_value = True
        related_units.return_value = ['ha/0', 'ha/1', 'ha/2']
        get_cluster_nodes.return_value = ['10.0.3.2', '10.0.3.3', '10.0.3.4']
        relation_ids.return_value = ['hanode:1']
        get_corosync_conf.return_value = True
        cfg = {'debug': False,
               'prefer-ipv6': False,
               'corosync_transport': 'udpu',
               'corosync_mcastaddr': 'corosync_mcastaddr',
               'cluster_count': 3}

        def c(k):
            return cfg.get(k)

        config.side_effect = c

        rel_get_data = {'locations': {'loc_foo': 'bar rule inf: meh eq 1'},
                        'clones': {'cl_foo': 'res_foo meta interleave=true'},
                        'groups': {'grp_foo': 'res_foo'},
                        'colocations': {'co_foo': 'inf: grp_foo cl_foo'},
                        'resources': {'res_foo': 'ocf:heartbeat:IPaddr2',
                                      'res_bar': 'ocf:heartbear:IPv6addr'},
                        'resource_params': {'res_foo': 'params bar'},
                        'ms': {'ms_foo': 'res_foo meta notify=true'},
                        'orders': {'foo_after': 'inf: res_foo ms_foo'}}

        def fake_parse_data(relid, unit, key):
            return rel_get_data.get(key, {})

        parse_data.side_effect = fake_parse_data

        hacluster_hooks.configure_principle_cluster_resources()
        relation_set.assert_any_call(relation_id='hanode:1', ready=True)
        configure_stonith.assert_called_with()
        configure_monitor_host.assert_called_with()
        configure_cluster_global.assert_called_with()
        configure_corosync.assert_called_with()

        for kw, key in [('location', 'locations'),
                        ('clone', 'clones'),
                        ('group', 'groups'),
                        ('colocation', 'colocations'),
                        ('primitive', 'resources'),
                        ('ms', 'ms'),
                        ('order', 'orders')]:
            for name, params in rel_get_data[key].items():
                if name in rel_get_data['resource_params']:
                    res_params = rel_get_data['resource_params'][name]
                    commit.assert_any_call(
                        'crm -w -F configure %s %s %s %s' % (kw, name, params,
                                                             res_params))
                else:
                    commit.assert_any_call(
                        'crm -w -F configure %s %s %s' % (kw, name, params))
