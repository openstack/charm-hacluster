#!/usr/bin/env python
import os
import amulet

import keystoneclient.v2_0 as keystone_client

from charmhelpers.contrib.openstack.amulet.deployment import (
    OpenStackAmuletDeployment
)
from charmhelpers.contrib.openstack.amulet.utils import (
    OpenStackAmuletUtils,
    DEBUG,
    # ERROR
)

# Use DEBUG to turn on debug logging
u = OpenStackAmuletUtils(DEBUG)
seconds_to_wait = 600


class HAClusterBasicDeployment(OpenStackAmuletDeployment):

    def __init__(self, series=None, openstack=None, source=None, stable=False):
        """Deploy the entire test environment."""
        super(HAClusterBasicDeployment, self).__init__(series, openstack,
                                                       source, stable)
        env_var = 'AMULET_OS_VIP'
        self._vip = os.getenv(env_var, None)
        if not self._vip:
            amulet.raise_status(amulet.SKIP, msg="No vip provided with '%s' - "
                                "skipping tests" % (env_var))

        self._add_services()
        self._add_relations()
        self._configure_services()
        self._deploy()

        u.log.info('Waiting on extended status checks...')
        exclude_services = ['mysql']

        # Wait for deployment ready msgs, except exclusions
        self._auto_wait_for_status(exclude_services=exclude_services)

        self._initialize_tests()

    def _add_services(self):
        this_service = {'name': 'hacluster'}
        other_services = [{'name': 'mysql'},
                          {'name': 'keystone', 'units': 3}]
        super(HAClusterBasicDeployment, self)._add_services(this_service,
                                                            other_services)

    def _add_relations(self):
        relations = {'keystone:shared-db': 'mysql:shared-db',
                     'hacluster:ha': 'keystone:ha'}
        super(HAClusterBasicDeployment, self)._add_relations(relations)

    def _configure_services(self):
        keystone_config = {'admin-password': 'openstack',
                           'admin-token': 'ubuntutesting',
                           'debug': 'true',
                           'verbose': 'true',
                           'vip': self._vip}
        mysql_config = {'dataset-size': '50%'}
        hacluster_config = {'debug': 'true'}
        configs = {'keystone': keystone_config,
                   'hacluster': hacluster_config,
                   'mysql': mysql_config}
        super(HAClusterBasicDeployment, self)._configure_services(configs)

    def _authenticate_keystone_admin(self, keystone_sentry, user, password,
                                     tenant, service_ip=None):
        """Authenticates admin user with the keystone admin endpoint.

        This should be factored into:L

            charmhelpers.contrib.openstack.amulet.utils.OpenStackAmuletUtils
        """
        if not service_ip:
            unit = keystone_sentry
            service_ip = unit.relation('shared-db',
                                       'mysql:shared-db')['private-address']

        ep = "http://{}:35357/v2.0".format(service_ip.strip().decode('utf-8'))
        return keystone_client.Client(username=user, password=password,
                                      tenant_name=tenant, auth_url=ep)

    def _initialize_tests(self):
        """Perform final initialization before tests get run."""
        # Access the sentries for inspecting service units
        self.mysql_sentry = self.d.sentry['mysql'][0]
        self.keystone_sentry = self.d.sentry['keystone'][0]
        # NOTE: the hacluster unit id may not correspond with its parent unit
        #       id.
        self.hacluster_sentry = self.d.sentry['hacluster'][0]

        u.log.debug('openstack release val: {}'.format(
            self._get_openstack_release()))
        u.log.debug('openstack release str: {}'.format(
            self._get_openstack_release_string()))

        # Authenticate keystone admin
        u.log.debug('Authenticating keystone admin against VIP: '
                    '{}'.format(self._vip))
        self.keystone = self._authenticate_keystone_admin(self.keystone_sentry,
                                                          user='admin',
                                                          password='openstack',
                                                          tenant='admin',
                                                          service_ip=self._vip)

        # Create a demo tenant/role/user
        u.log.debug('Creating keystone demo tenant, role and user against '
                    'VIP: {}'.format(self._vip))
        self.demo_tenant = 'demoTenant'
        self.demo_role = 'demoRole'
        self.demo_user = 'demoUser'
        if not u.tenant_exists(self.keystone, self.demo_tenant):
            tenant = self.keystone.tenants.create(tenant_name=self.demo_tenant,
                                                  description='demo tenant',
                                                  enabled=True)
            self.keystone.roles.create(name=self.demo_role)
            self.keystone.users.create(name=self.demo_user,
                                       password='password',
                                       tenant_id=tenant.id,
                                       email='demo@demo.com')

        # Authenticate keystone demo
        u.log.debug('Authenticating keystone demo user against VIP: '
                    '{}'.format(self._vip))
        self.keystone_demo = u.authenticate_keystone_user(
            self.keystone,
            user=self.demo_user,
            password='password',
            tenant=self.demo_tenant)
