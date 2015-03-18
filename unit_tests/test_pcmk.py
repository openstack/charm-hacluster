#
# Copyright 2015 Canonical Ltd.
#
# Authors:
#  Felipe Reyes <felipe.reyes@canonical.com>
#

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
