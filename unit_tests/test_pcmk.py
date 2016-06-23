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
import unittest


class TestPcmk(unittest.TestCase):
    @mock.patch('commands.getstatusoutput')
    def test_crm_res_running_true(self, getstatusoutput):
        getstatusoutput.return_value = (0, ("resource res_nova_consoleauth is "
                                            "running on: juju-xxx-machine-6"))
        self.assertTrue(pcmk.crm_res_running('res_nova_consoleauth'))

    @mock.patch('commands.getstatusoutput')
    def test_crm_res_running_stopped(self, getstatusoutput):
        getstatusoutput.return_value = (0, ("resource res_nova_consoleauth is "
                                            "NOT running"))
        self.assertFalse(pcmk.crm_res_running('res_nova_consoleauth'))

    @mock.patch('commands.getstatusoutput')
    def test_crm_res_running_undefined(self, getstatusoutput):
        getstatusoutput.return_value = (1, "foobar")
        self.assertFalse(pcmk.crm_res_running('res_nova_consoleauth'))
