
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
import sys
import fcntl
import struct
import time


def do_hooks(hooks):
    hook = os.path.basename(sys.argv[0])

    try:
        hooks[hook]()
    except KeyError:
        juju_log('INFO',
                 "This charm doesn't know how to handle '{}'.".format(hook))


def can_install():
    try:
        fd = os.open("/var/lib/dpkg/lock", os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0640)
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError, message:
        os.close(fd)
        return False
    else:
        fcntl.lockf(fd, fcntl.LOCK_UN)
        os.close(fd)
        return True


def install(*pkgs):
    cmd = [
        'apt-get',
        '-y',
        'install'
          ]
    for pkg in pkgs:
        cmd.append(pkg)
    while not can_install():
        juju_log('INFO',
                 "dpkg is busy, can't install %s yet, waiting..." % pkgs)
        time.sleep(1)
    subprocess.check_call(cmd)

TEMPLATES_DIR = 'templates'

try:
    import jinja2
except ImportError:
    install('python-jinja2')
    import jinja2

try:
    from netaddr import IPNetwork
except ImportError:
    install('python-netaddr')
    from netaddr import IPNetwork

try:
    import dns.resolver
except ImportError:
    install('python-dnspython')
    import dns.resolver


def render_template(template_name, context, template_dir=TEMPLATES_DIR):
    templates = jinja2.Environment(
                    loader=jinja2.FileSystemLoader(template_dir)
                    )
    template = templates.get_template(template_name)
    return template.render(context)


CLOUD_ARCHIVE = \
""" # Ubuntu Cloud Archive
deb http://ubuntu-cloud.archive.canonical.com/ubuntu {} main
"""

CLOUD_ARCHIVE_POCKETS = {
    'precise-folsom': 'precise-updates/folsom',
    'precise-folsom/updates': 'precise-updates/folsom',
    'precise-folsom/proposed': 'precise-proposed/folsom',
    'precise-grizzly': 'precise-updates/grizzly',
    'precise-grizzly/updates': 'precise-updates/grizzly',
    'precise-grizzly/proposed': 'precise-proposed/grizzly'
    }


def configure_source():
    source = str(config_get('openstack-origin'))
    if not source:
        return
    if source.startswith('ppa:'):
        cmd = [
            'add-apt-repository',
            source
            ]
        subprocess.check_call(cmd)
    if source.startswith('cloud:'):
        install('ubuntu-cloud-keyring')
        pocket = source.split(':')[1]
        with open('/etc/apt/sources.list.d/cloud-archive.list', 'w') as apt:
            apt.write(CLOUD_ARCHIVE.format(CLOUD_ARCHIVE_POCKETS[pocket]))
    if source.startswith('deb'):
        l = len(source.split('|'))
        if l == 2:
            (apt_line, key) = source.split('|')
            cmd = [
                'apt-key',
                'adv', '--keyserver keyserver.ubuntu.com',
                '--recv-keys', key
                ]
            subprocess.check_call(cmd)
        elif l == 1:
            apt_line = source

        with open('/etc/apt/sources.list.d/quantum.list', 'w') as apt:
            apt.write(apt_line + "\n")
    cmd = [
        'apt-get',
        'update'
        ]
    subprocess.check_call(cmd)

# Protocols
TCP = 'TCP'
UDP = 'UDP'


def expose(port, protocol='TCP'):
    cmd = [
        'open-port',
        '{}/{}'.format(port, protocol)
        ]
    subprocess.check_call(cmd)


def juju_log(severity, message):
    cmd = [
        'juju-log',
        '--log-level', severity,
        message
        ]
    subprocess.check_call(cmd)


def relation_ids(relation):
    cmd = [
        'relation-ids',
        relation
        ]
    return subprocess.check_output(cmd).split()  # IGNORE:E1103


def relation_list(rid):
    cmd = [
        'relation-list',
        '-r', rid,
        ]
    return subprocess.check_output(cmd).split()  # IGNORE:E1103


def relation_get(attribute, unit=None, rid=None):
    cmd = [
        'relation-get',
        ]
    if rid:
        cmd.append('-r')
        cmd.append(rid)
    cmd.append(attribute)
    if unit:
        cmd.append(unit)
    value = subprocess.check_output(cmd).strip()  # IGNORE:E1103
    if value == "":
        return None
    else:
        return value


def relation_set(**kwargs):
    cmd = [
        'relation-set'
        ]
    args = []
    for k, v in kwargs.items():
        if k == 'rid':
            cmd.append('-r')
            cmd.append(v)
        else:
            args.append('{}={}'.format(k, v))
    cmd += args
    subprocess.check_call(cmd)


def unit_get(attribute):
    cmd = [
        'unit-get',
        attribute
        ]
    return subprocess.check_output(cmd).strip()  # IGNORE:E1103


def config_get(attribute):
    cmd = [
        'config-get',
        attribute
        ]
    return subprocess.check_output(cmd).strip()  # IGNORE:E1103


def get_unit_hostname():
    return socket.gethostname()


def get_host_ip(hostname=unit_get('private-address')):
    try:
        # Test to see if already an IPv4 address
        socket.inet_aton(hostname)
        return hostname
    except socket.error:
        pass
    try:
        answers = dns.resolver.query(hostname, 'A')
        if answers:
            return answers[0].address
    except dns.resolver.NXDOMAIN:
        pass
    return None


def restart(*services):
    for service in services:
        subprocess.check_call(['service', service, 'restart'])


def stop(*services):
    for service in services:
        subprocess.check_call(['service', service, 'stop'])


def start(*services):
    for service in services:
        subprocess.check_call(['service', service, 'start'])


def running(service):
    try:
        output = subprocess.check_output(['service', service, 'status'])
    except subprocess.CalledProcessError:
        return False
    else:
        if ("start/running" in output or
            "is running" in output):
            return True
        else:
            return False


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
