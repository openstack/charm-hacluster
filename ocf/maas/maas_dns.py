#!/usr/bin/python3
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

import maasclient
import argparse
import sys
import logging


class MAASDNS(object):
    def __init__(self, options):
        self.maas = maasclient.MAASClient(options.maas_server,
                                          options.maas_credentials)
        # String representation of the fqdn
        self.fqdn = options.fqdn
        # Dictionary representation of MAAS dnsresource object
        # TODO: Do this as a property
        self.dnsresource = self.get_dnsresource()
        # String representation of the time to live
        self.ttl = str(options.ttl)
        # String representation of the ip
        self.ip = options.ip_address

    def get_dnsresource(self):
        """ Get a dnsresource object """
        dnsresources = self.maas.get_dnsresources()
        self.dnsresource = None
        for dnsresource in dnsresources:
            if dnsresource['fqdn'] == self.fqdn:
                self.dnsresource = dnsresource
        return self.dnsresource

    def get_dnsresource_id(self):
        """ Get a dnsresource ID """
        return self.dnsresource['id']

    def update_resource(self):
        """ Update a dnsresource record with an IP """
        return self.maas.update_dnsresource(self.dnsresource['id'],
                                            self.dnsresource['fqdn'],
                                            self.ip)

    def create_dnsresource(self):
        """ Create a DNS resource object
        Due to https://bugs.launchpad.net/maas/+bug/1555393
        This is currently unused
        """
        return self.maas.create_dnsresource(self.fqdn,
                                            self.ip,
                                            self.ttl)


class MAASIP(object):
    def __init__(self, options):
        self.maas = maasclient.MAASClient(options.maas_server,
                                          options.maas_credentials)
        # String representation of the IP
        self.ip = options.ip_address
        # Dictionary representation of MAAS ipaddresss object
        # TODO: Do this as a property
        self.ipaddress = self.get_ipaddress()

    def get_ipaddress(self):
        """ Get an ipaddresses object """
        ipaddresses = self.maas.get_ipaddresses()
        self.ipaddress = None
        for ipaddress in ipaddresses:
            if ipaddress['ip'] == self.ip:
                self.ipaddress = ipaddress
        return self.ipaddress

    def create_ipaddress(self, hostname=None):
        """ Create an ipaddresses object
        Due to https://bugs.launchpad.net/maas/+bug/1555393
        This is currently unused
        """
        return self.maas.create_ipaddress(self.ip, hostname)


def setup_logging(logfile, log_level='INFO'):
    logFormatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")
    rootLogger = logging.getLogger()
    rootLogger.setLevel(log_level)

    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(logFormatter)
    rootLogger.addHandler(consoleHandler)

    try:
        fileLogger = logging.getLogger('file')
        fileLogger.propagate = False

        fileHandler = logging.FileHandler(logfile)
        fileHandler.setFormatter(logFormatter)
        rootLogger.addHandler(fileHandler)
        fileLogger.addHandler(fileHandler)
    except IOError:
        logging.error('Unable to write to logfile: {}'.format(logfile))


def dns_ha():

    parser = argparse.ArgumentParser()
    parser.add_argument('--maas_server', '-s',
                        help='URL to mangage the MAAS server',
                        required=True)
    parser.add_argument('--maas_credentials', '-c',
                        help='MAAS OAUTH credentials',
                        required=True)
    parser.add_argument('--fqdn', '-d',
                        help='Fully Qualified Domain Name',
                        required=True)
    parser.add_argument('--ip_address', '-i',
                        help='IP Address, target of the A record',
                        required=True)
    parser.add_argument('--ttl', '-t',
                        help='DNS Time To Live in seconds',
                        default='')
    parser.add_argument('--logfile', '-l',
                        help='Path to logfile',
                        default='/var/log/{}.log'
                                ''.format(sys.argv[0]
                                          .split('/')[-1]
                                          .split('.')[0]))
    options = parser.parse_args()

    setup_logging(options.logfile)
    logging.info("Starting maas_dns")

    dns_obj = MAASDNS(options)
    if not dns_obj.dnsresource:
        logging.info('DNS Resource does not exist. '
                     'Create it with the maas cli.')
    elif dns_obj.dnsresource.get('ip_addresses'):
        # TODO: Handle multiple IPs returned for ip_addresses
        for ip in dns_obj.dnsresource['ip_addresses']:
            if ip.get('ip') != options.ip_address:
                logging.info('Update the dnsresource with IP: {}'
                             ''.format(options.ip_address))
                dns_obj.update_resource()
            else:
                logging.info('IP is the SAME {}, no update required'
                             ''.format(options.ip_address))
    else:
        logging.info('Update the dnsresource with IP: {}'
                     ''.format(options.ip_address))
        dns_obj.update_resource()


if __name__ == '__main__':
    dns_ha()
