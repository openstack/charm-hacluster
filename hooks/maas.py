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

import apt_pkg as apt

import json
import subprocess

from charmhelpers.fetch import apt_install
from charmhelpers.core.hookenv import (
    log,
    ERROR,
)

MAAS_STABLE_PPA = 'ppa:maas-maintainers/stable '
MAAS_PROFILE_NAME = 'maas-juju-hacluster'


class MAASHelper(object):

    def __init__(self, url, creds):
        self.url = url
        self.creds = creds
        self.install_maas_cli()

    def install_maas_cli(self):
        """Ensure maas-cli is installed

        Fallback to MAAS stable PPA when needed.
        """
        apt.init()
        cache = apt.Cache()

        try:
            pkg = cache['maas-cli']
        except KeyError:
            cmd = ['add-apt-repository', '-y', MAAS_STABLE_PPA]
            subprocess.check_call(cmd)
            cmd = ['apt-get', 'update']
            subprocess.check_call(cmd)
            self.install_maas_cli()
            return

        if not pkg.current_ver:
            apt_install('maas-cli', fatal=True)

    def login(self):
        cmd = ['maas-cli', 'login', MAAS_PROFILE_NAME, self.url, self.creds]
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError:
            log('Could not login to MAAS @ %s.' % self.url, ERROR)
            return False

    def logout(self):
        cmd = ['maas-cli', 'logout', MAAS_PROFILE_NAME]
        subprocess.check_call(cmd)

    def list_nodes(self):
        self.login()

        try:
            cmd = ['maas-cli', MAAS_PROFILE_NAME, 'nodes', 'list']
            out = subprocess.check_output(cmd)
        except subprocess.CalledProcessError:
            log('Could not get node inventory from MAAS.', ERROR)
            return False

        self.logout()
        return json.loads(out)
