#!/usr/bin/python
#
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

import sys
import os
import subprocess
import traceback
sys.path.append('hooks/')
from charmhelpers.core.hookenv import (
    action_fail,
    action_get,
    action_set,
    log,
)
from utils import (
    pause_unit,
    resume_unit,
)


def pause(args):
    """Pause the hacluster services.
    @raises Exception should the service fail to stop.
    """
    pause_unit()


def resume(args):
    """Resume the hacluster services.
    @raises Exception should the service fail to start."""
    resume_unit()


def status(args):
    """Display status of cluster resources.
    Includes inactive resources in results."""
    cmd = ['crm', 'status', '--inactive']

    try:
        result = subprocess.check_output(cmd)
        action_set({'result': result})
    except subprocess.CalledProcessError as e:
        log("ERROR: Failed call to crm resource status. "
            "output: {}. return-code: {}".format(e.output, e.returncode))
        log(traceback.format_exc())
        action_set({'result': ''})
        action_fail("failed to get cluster status")


def cleanup(args):
    """Cleanup an/all hacluster resource(s).
        Optional arg "resource=res_xyz_abc" """
    resource_name = (action_get("resource")).lower()
    if resource_name == 'all':
        cmd = ['crm_resource', '-C']
    else:
        cmd = ['crm', 'resource', 'cleanup', resource_name]

    try:
        subprocess.check_call(cmd)
        action_set({'result': 'success'})
    except subprocess.CalledProcessError as e:
        log("ERROR: Failed call to crm resource cleanup for {}. "
            "output: {}. return-code: {}".format(resource_name, e.output,
                                                 e.returncode))
        log(traceback.format_exc())
        action_set({'result': 'failure'})
        action_fail("failed to cleanup crm resource "
                    "'{}'".format(resource_name))


ACTIONS = {"pause": pause, "resume": resume,
           "status": status, "cleanup": cleanup}


def main(args):
    action_name = os.path.basename(args[0])
    try:
        action = ACTIONS[action_name]
    except KeyError:
        return "Action %s undefined" % action_name
    else:
        try:
            action(args)
        except Exception as e:
            action_fail(str(e))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
