
#
# Copyright 2012 Canonical Ltd.
#
# Authors:
#  James Page <james.page@ubuntu.com>
#  Paul Collins <paul.collins@canonical.com>
#

import os
import subprocess
import socket
import fcntl
import struct
from charmhelpers.fetch import apt_install

try:
    from netaddr import IPNetwork
except ImportError:
    apt_install('python-netaddr', fatal=True)
    from netaddr import IPNetwork


def disable_upstart_services(*services):
    for service in services:
        with open("/etc/init/{}.override".format(service), "w") as override:
            override.write("manual")


def enable_upstart_services(*services):
    for service in services:
        path = '/etc/init/{}.override'.format(service)
        if os.path.exists(path):
            os.remove(path)


def disable_lsb_services(*services):
    for service in services:
        subprocess.check_call(['update-rc.d', '-f', service, 'remove'])


def enable_lsb_services(*services):
    for service in services:
        subprocess.check_call(['update-rc.d', '-f', service, 'defaults'])


def get_iface_ipaddr(iface):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
        s.fileno(),
        0x8919,  # SIOCGIFADDR
        struct.pack('256s', iface[:15])
    )[20:24])


def get_iface_netmask(iface):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
        s.fileno(),
        0x891b,  # SIOCGIFNETMASK
        struct.pack('256s', iface[:15])
    )[20:24])


def get_netmask_cidr(netmask):
    netmask = netmask.split('.')
    binary_str = ''
    for octet in netmask:
        binary_str += bin(int(octet))[2:].zfill(8)
    return str(len(binary_str.rstrip('0')))


def get_network_address(iface):
    if iface:
        network = "{}/{}".format(get_iface_ipaddr(iface),
                                 get_netmask_cidr(get_iface_netmask(iface)))
        ip = IPNetwork(network)
        return str(ip.network)
    else:
        return None