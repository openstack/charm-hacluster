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
import pcmk
import os
import tempfile
import unittest
from distutils.version import StrictVersion
from charmhelpers.core import unitdata


CRM_CONFIGURE_SHOW_XML = '''<?xml version="1.0" ?>
<cib num_updates="1" dc-uuid="1002" update-origin="juju-34fde5-0" crm_feature_set="3.0.7" validate-with="pacemaker-1.2" update-client="cibadmin" epoch="1103" admin_epoch="0" cib-last-written="Fri Aug  4 13:45:06 2017" have-quorum="1">
  <configuration>
    <crm_config>
      <cluster_property_set id="cib-bootstrap-options">
        <nvpair id="cib-bootstrap-options-dc-version" name="dc-version" value="1.1.10-42f2063"/>
        <nvpair id="cib-bootstrap-options-cluster-infrastructure" name="cluster-infrastructure" value="corosync"/>
        <nvpair name="no-quorum-policy" value="stop" id="cib-bootstrap-options-no-quorum-policy"/>
        <nvpair name="stonith-enabled" value="false" id="cib-bootstrap-options-stonith-enabled"/>
      </cluster_property_set>
    </crm_config>
    <nodes>
      <node id="1002" uname="juju-34fde5-0"/>
    </nodes>
    <resources/>
    <constraints/>
    <rsc_defaults>
      <meta_attributes id="rsc-options">
        <nvpair name="resource-stickiness" value="100" id="rsc-options-resource-stickiness"/>
      </meta_attributes>
    </rsc_defaults>
  </configuration>
</cib>

'''  # noqa

CRM_CONFIGURE_SHOW_XML_MAINT_MODE_TRUE = '''<?xml version="1.0" ?>
<cib num_updates="1" dc-uuid="1002" update-origin="juju-34fde5-0" crm_feature_set="3.0.7" validate-with="pacemaker-1.2" update-client="cibadmin" epoch="1103" admin_epoch="0" cib-last-written="Fri Aug  4 13:45:06 2017" have-quorum="1">
  <configuration>
    <crm_config>
      <cluster_property_set id="cib-bootstrap-options">
        <nvpair id="cib-bootstrap-options-dc-version" name="dc-version" value="1.1.10-42f2063"/>
        <nvpair id="cib-bootstrap-options-cluster-infrastructure" name="cluster-infrastructure" value="corosync"/>
        <nvpair name="no-quorum-policy" value="stop" id="cib-bootstrap-options-no-quorum-policy"/>
        <nvpair name="stonith-enabled" value="false" id="cib-bootstrap-options-stonith-enabled"/>
        <nvpair name="maintenance-mode" value="true" id="cib-bootstrap-options-maintenance-mode"/>
      </cluster_property_set>
    </crm_config>
    <nodes>
      <node id="1002" uname="juju-34fde5-0"/>
    </nodes>
    <resources/>
    <constraints/>
    <rsc_defaults>
      <meta_attributes id="rsc-options">
        <nvpair name="resource-stickiness" value="100" id="rsc-options-resource-stickiness"/>
      </meta_attributes>
    </rsc_defaults>
  </configuration>
</cib>

'''  # noqa

CRM_NODE_STATUS_XML = b'''
<nodes>
  <node id="1000" uname="juju-982848-zaza-ce47c58f6c88-10"/>
  <node id="1001" uname="juju-982848-zaza-ce47c58f6c88-9"/>
  <node id="1002" uname="juju-982848-zaza-ce47c58f6c88-11"/>
</nodes>
'''


class TestPcmk(unittest.TestCase):
    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(delete=False)

    def tearDown(self):
        os.remove(self.tmpfile.name)

    @mock.patch('subprocess.getstatusoutput')
    def test_crm_res_running_true(self, getstatusoutput):
        getstatusoutput.return_value = (0, ("resource res_nova_consoleauth is "
                                            "running on: juju-xxx-machine-6"))
        self.assertTrue(pcmk.crm_res_running('res_nova_consoleauth'))

    @mock.patch('subprocess.getstatusoutput')
    def test_crm_res_running_stopped(self, getstatusoutput):
        getstatusoutput.return_value = (0, ("resource res_nova_consoleauth is "
                                            "NOT running"))
        self.assertFalse(pcmk.crm_res_running('res_nova_consoleauth'))

    @mock.patch('subprocess.getstatusoutput')
    def test_crm_res_running_undefined(self, getstatusoutput):
        getstatusoutput.return_value = (1, "foobar")
        self.assertFalse(pcmk.crm_res_running('res_nova_consoleauth'))

    @mock.patch('subprocess.getstatusoutput')
    def test_crm_res_running_on_node(self, getstatusoutput):
        _resource = "res_nova_consoleauth"
        _this_node = "node1"
        _another_node = "node5"

        # Not running
        getstatusoutput.return_value = (1, "foobar")
        self.assertFalse(
            pcmk.crm_res_running_on_node(_resource, _this_node))

        # Running active/passive on some other node
        getstatusoutput.return_value = (
            0, "resource {} is running: {}".format(_resource, _another_node))
        self.assertTrue(
            pcmk.crm_res_running_on_node('res_nova_consoleauth', _this_node))

        # Running active/passive on this node
        getstatusoutput.return_value = (
            0, "resource {} is running: {}".format(_resource, _this_node))
        self.assertTrue(
            pcmk.crm_res_running_on_node('res_nova_consoleauth', _this_node))

        # Running on some but not this node
        getstatusoutput.return_value = (
            0, ("resource {} is running: {}\nresource {} is NOT running"
                .format(_resource, _another_node, _resource)))
        self.assertFalse(
            pcmk.crm_res_running_on_node('res_nova_consoleauth', _this_node))

        # Running on this node and not others
        getstatusoutput.return_value = (
            0, ("resource {} is running: {}\nresource {} is NOT running"
                .format(_resource, _this_node, _resource)))
        self.assertTrue(
            pcmk.crm_res_running_on_node('res_nova_consoleauth', _this_node))

        # Running on more than one and this node
        getstatusoutput.return_value = (
            0, ("resource {} is running: {}\nresource {} is running: {}"
                .format(_resource, _another_node, _resource, _this_node)))
        self.assertTrue(
            pcmk.crm_res_running_on_node('res_nova_consoleauth', _this_node))

    @mock.patch('socket.gethostname')
    @mock.patch('subprocess.getstatusoutput')
    def test_wait_for_pcmk(self, getstatusoutput, gethostname):
        # Pacemaker is down
        gethostname.return_value = 'hanode-1'
        getstatusoutput.return_value = (1, 'Not the hostname')
        with self.assertRaises(pcmk.ServicesNotUp):
            pcmk.wait_for_pcmk(retries=2, sleep=0)

        # Pacemaker is up
        gethostname.return_value = 'hanode-1'
        getstatusoutput.return_value = (0, 'Hosname: hanode-1')
        self.assertTrue(pcmk.wait_for_pcmk(retries=2, sleep=0))

    @mock.patch('subprocess.check_output')
    def test_crm_version(self, mock_check_output):
        # xenial
        mock_check_output.return_value = "crm 2.2.0\n"
        ret = pcmk.crm_version()
        self.assertEqual(StrictVersion('2.2.0'), ret)
        mock_check_output.assert_called_with(['crm', '--version'],
                                             universal_newlines=True)

        # trusty
        mock_check_output.mock_reset()
        mock_check_output.return_value = (
            "1.2.5 (Build f2f315daf6a5fd7ddea8e564cd289aa04218427d)\n")
        ret = pcmk.crm_version()
        self.assertEqual(StrictVersion('1.2.5'), ret)
        mock_check_output.assert_called_with(['crm', '--version'],
                                             universal_newlines=True)

    @mock.patch('subprocess.check_output')
    @mock.patch.object(pcmk, 'crm_version')
    def test_get_property(self, mock_crm_version, mock_check_output):
        mock_crm_version.return_value = StrictVersion('2.2.0')  # xenial
        mock_check_output.return_value = 'false\n'
        self.assertEqual('false\n', pcmk.get_property('maintenance-mode'))

        mock_check_output.assert_called_with(['crm', 'configure',
                                              'show-property',
                                              'maintenance-mode'],
                                             universal_newlines=True)

        mock_crm_version.return_value = StrictVersion('2.4.0')
        mock_check_output.reset_mock()
        self.assertEqual('false\n', pcmk.get_property('maintenance-mode'))
        mock_check_output.assert_called_with(['crm', 'configure',
                                              'get-property',
                                              'maintenance-mode'],
                                             universal_newlines=True)

    @mock.patch('subprocess.check_output')
    @mock.patch.object(pcmk, 'crm_version')
    def test_get_property_from_xml(self, mock_crm_version, mock_check_output):
        mock_crm_version.return_value = StrictVersion('1.2.5')  # trusty
        mock_check_output.return_value = CRM_CONFIGURE_SHOW_XML
        self.assertRaises(pcmk.PropertyNotFound, pcmk.get_property,
                          'maintenance-mode')

        mock_check_output.assert_called_with(['crm', 'configure',
                                              'show', 'xml'],
                                             universal_newlines=True)
        mock_check_output.reset_mock()
        mock_check_output.return_value = CRM_CONFIGURE_SHOW_XML_MAINT_MODE_TRUE
        self.assertEqual('true', pcmk.get_property('maintenance-mode'))

        mock_check_output.assert_called_with(['crm', 'configure',
                                              'show', 'xml'],
                                             universal_newlines=True)

    @mock.patch('subprocess.check_call')
    def test_set_property(self, mock_check_output):
        pcmk.set_property('maintenance-mode', 'false')
        mock_check_output.assert_called_with(['crm', 'configure', 'property',
                                              'maintenance-mode=false'],
                                             universal_newlines=True)

    @mock.patch('subprocess.call')
    def test_crm_update_resource(self, mock_call):
        db = unitdata.kv()
        db.set('res_test-IPaddr2', '')
        mock_call.return_value = 0

        with mock.patch.object(tempfile, "NamedTemporaryFile",
                               side_effect=lambda: self.tmpfile):
            pcmk.crm_update_resource('res_test', 'IPaddr2',
                                     ('params ip=1.2.3.4 '
                                      'cidr_netmask=255.255.0.0'))

        mock_call.assert_any_call(['crm', 'configure', 'load',
                                   'update', self.tmpfile.name])
        with open(self.tmpfile.name, 'rt') as f:
            self.assertEqual(f.read(),
                             ('primitive res_test IPaddr2 \\\n'
                              '\tparams ip=1.2.3.4 cidr_netmask=255.255.0.0'))

    @mock.patch('subprocess.call')
    def test_crm_update_resource_exists_in_kv(self, mock_call):
        db = unitdata.kv()
        db.set('res_test-IPaddr2', 'ef395293b1b7c29c5bf1c99774f75cf4')

        pcmk.crm_update_resource('res_test', 'IPaddr2',
                                 'params ip=1.2.3.4 cidr_netmask=255.0.0.0')

        mock_call.assert_called_once_with([
            'juju-log',
            "Resource res_test already defined and parameters haven't changed"
        ])

    @mock.patch('subprocess.call')
    def test_crm_update_resource_exists_in_kv_force_true(self, mock_call):
        db = unitdata.kv()
        db.set('res_test-IPaddr2', 'ef395293b1b7c29c5bf1c99774f75cf4')

        with mock.patch.object(tempfile, "NamedTemporaryFile",
                               side_effect=lambda: self.tmpfile):
            pcmk.crm_update_resource('res_test', 'IPaddr2',
                                     ('params ip=1.2.3.4 '
                                      'cidr_netmask=255.0.0.0'),
                                     force=True)

        mock_call.assert_any_call(['crm', 'configure', 'load',
                                   'update', self.tmpfile.name])

    def test_resource_checksum(self):
        r = pcmk.resource_checksum('res_test', 'IPaddr2',
                                   'params ip=1.2.3.4 cidr_netmask=255.0.0.0')
        self.assertEqual(r, 'ef395293b1b7c29c5bf1c99774f75cf4')

    @mock.patch('subprocess.check_output', return_value=CRM_NODE_STATUS_XML)
    def test_list_nodes(self, mock_check_output):
        self.assertSequenceEqual(
            pcmk.list_nodes(),
            [
                'juju-982848-zaza-ce47c58f6c88-10',
                'juju-982848-zaza-ce47c58f6c88-11',
                'juju-982848-zaza-ce47c58f6c88-9'])
        mock_check_output.assert_called_once_with(['crm', 'node', 'status'])
