import apt_pkg as apt

import json
import sys
import subprocess

import utils

MAAS_STABLE_PPA = 'ppa:maas-maintainers/stable '
MAAS_PROFILE_NAME = 'maas-juju-hacluster'

class MAASHelper(object):
    def __init__(url, creds):
        self.url = url
        self.creds = creds
        self.install_maas_cli()

    def install_maas_cli(self):
        '''
        Ensure maas-cli is installed.  Fallback to MAAS stable PPA when
        needed.
        '''
        apt.init()
        cache = apt.Cache()

        try:
            pkg = cache['maas-cli']
        except KeyError:
            cmd = ['add-apt-repository', '-y', MAAS_STABLE_PPA]
            subprocess.check_call(cmd)
            cmd = ['apt-get', 'update']
            subprocess.check_call(cmd)
            install_maas_cli()
            return

        if not pkg.current_ver:
            utils.install('maas-cli')


    def login(self):
        cmd = ['maas-cli', 'login', MAAS_PROFILE_NAME, self.url, self.creds]
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError:
            utils.juju_log('ERROR', 'Could not login to MAAS @ %s.' % url)
            return False


    def logout(self):
        cmd = ['maas-cli', 'logout', MAAS_PROFILE_NAME]
        subprocess.check_call(cmd)


    def list_nodes():
        self.login()

        try:
            cmd = ['maas-cli', MAAS_PROFILE_NAME, 'nodes', 'list']
            out = subprocess.check_output(cmd)
        except subprocess.CalledProcessError:
            utils.juju_log('ERROR', 'Could not get node inventory from MAAS.')
            return False
        self.logout()
        return json.loads(out)
