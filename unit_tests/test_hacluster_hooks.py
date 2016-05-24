import mock
import os
import sys
import tempfile
import unittest


mock_apt = mock.MagicMock()
sys.modules['apt_pkg'] = mock_apt
import hooks


@mock.patch.object(hooks, 'log', lambda *args, **kwargs: None)
@mock.patch('utils.COROSYNC_CONF', os.path.join(tempfile.mkdtemp(),
                                                'corosync.conf'))
class TestCorosyncConf(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    @mock.patch('pcmk.wait_for_pcmk')
    @mock.patch.object(hooks, 'peer_units')
    @mock.patch('pcmk.crm_opt_exists')
    @mock.patch.object(hooks, 'oldest_peer')
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
                                 oldest_peer, crm_opt_exists, peer_units,
                                 wait_for_pcmk):
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

        config.side_effect = lambda key: cfg.get(key)

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

        hooks.ha_relation_changed()
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
