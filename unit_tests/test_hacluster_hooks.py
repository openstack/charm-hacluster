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
