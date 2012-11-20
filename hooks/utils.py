
#
# Copyright 2012 Canonical Ltd.
#
# Authors:
#  James Page <james.page@ubuntu.com>
#  Paul Collins <paul.collins@canonical.com>
#

import commands
import os
import re
import subprocess
import socket
import sys


def do_hooks(hooks):
    hook = os.path.basename(sys.argv[0])

    try:
        hooks[hook]()
    except KeyError:
        juju_log('INFO',
                 "This charm doesn't know how to handle '{}'.".format(hook))


def install(*pkgs):
    cmd = [
        'apt-get',
        '-y',
        'install'
          ]
    for pkg in pkgs:
        cmd.append(pkg)
    subprocess.check_call(cmd)

TEMPLATES_DIR = 'templates'

try:
    import jinja2
except ImportError:
    install('python-jinja2')
    import jinja2


def render_template(template_name, context, template_dir=TEMPLATES_DIR):
    templates = jinja2.Environment(
                    loader=jinja2.FileSystemLoader(template_dir)
                    )
    template = templates.get_template(template_name)
    return template.render(context)


def configure_source():
    source = config_get('source')
    if (source.startswith('ppa:') or
        source.startswith('cloud:')):
        cmd = [
            'add-apt-repository',
            source
            ]
        subprocess.check_call(cmd)
    if source.startswith('http:'):
        with open('/etc/apt/sources.list.d/hacluster.list', 'w') as apt:
            apt.write("deb " + source + "\n")
        key = config_get('key')
        if key != "":
            cmd = [
                'apt-key',
                'import',
                key
                ]
            subprocess.check_call(cmd)
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
    cmd = [
        'dig',
        '+short',
        hostname
        ]
    return subprocess.check_output(cmd).strip()  # IGNORE:E1103


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
    #output = subprocess.check_output(['service', service, 'status'])
    output = commands.getoutput('service %s status' % service)
    show_re = re.compile("start/running")
    status = show_re.search(output)
    if status:
        return True
    return False

def disable_upstart_services(*services):
    for service in services:
        #subprocess.check_call('sh -c "echo manual > /etc/init/%s.override"' % service, shell=True)
        override = open("/etc/init/%s.override" % service, "w")
        override.write("manual")
        override.close()


def enable_upstart_services(*services):
    for service in services:
        path = '/etc/init/%s.override' % service
        if os.path.exists(path):
            subprocess.check_call(['rm', '-rf', path])


def disable_lsb_services(*services):
    for service in services:
        subprocess.check_call(['update-rc.d', '-f', service, 'remove'])


def enable_lsb_services(*services):
    for service in services:
        subprocess.call(['update-rc.d','-f',service,'defaults'])
