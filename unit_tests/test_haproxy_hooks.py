import mock
import unittest

with mock.patch('charmhelpers.core.hookenv.config'):
    import hooks as hacluster_hooks


class SwiftContextTestCase(unittest.TestCase):

    @mock.patch('hooks.config')
    def test_get_transport(self, mock_config):
        mock_config.return_value = 'udp'
        self.assertEqual('udp', hacluster_hooks.get_transport())

        mock_config.return_value = 'udpu'
        self.assertEqual('udpu', hacluster_hooks.get_transport())

        mock_config.return_value = 'hafu'
        self.assertRaises(ValueError, hacluster_hooks.get_transport)
