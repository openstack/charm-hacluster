# Overview

The hacluster subordinate charm provides corosync and pacemaker cluster
configuration for principle charms which support the hacluster, container
scoped relation.

The charm will only configure for HA once more that one service unit is
present.

# Usage

NOTE: The hacluster subordinate charm requires multicast network support, so
this charm will NOT work in ec2 or in other clouds which block multicast
traffic.  Its intended for use in MAAS managed environments of physical
hardware.

To deploy the charm:

    juju deploy hacluster mysql-hacluster

To enable HA clustering support (for mysql for example):

    juju deploy -n 2 mysql
    juju deploy -n 3 ceph
    juju set mysql vip="192.168.21.1"
    juju add-relation mysql ceph
    juju add-relation mysql mysql-hacluster

The principle charm must have explicit support for the hacluster interface
in order for clustering to occur - otherwise nothing actually get configured.


# HA/Clustering

There are two mutually exclusive high availability options: using virtual
IP(s) or DNS.

To use virtual IP(s) the clustered nodes must be on the same subnet such that
the VIP is a valid IP on the subnet for one of the node's interfaces and each
node has an interface in said subnet. The VIP becomes a highly-available API
endpoint.

To use DNS high availability there are several prerequisites. However, DNS HA
does not require the clustered nodes to be on the same subnet.
Currently the DNS HA feature is only available for MAAS 2.0 or greater
environments. MAAS 2.0 requires Juju 2.0 or greater. The MAAS 2.0 client
requires Ubuntu 16.04 or greater. The clustered nodes must have static or
"reserved" IP addresses registered in MAAS. The DNS hostname(s) must be
pre-registered in MAAS before use with DNS HA.

The charm will throw an exception in the following circumstances:
If running on a version of Ubuntu less than Xenial 16.04

# Usage for Charm Authors

The hacluster interface supports a number of different cluster configuration
options.

## Mandatory Relation Data (deprecated)

Principle charms should provide basic corosync configuration:

    corosync\_bindiface: The network interface to use for cluster messaging.
    corosync\_mcastport: The multicast port to use for cluster messaging.

however, these can also be provided via configuration on the hacluster charm
itself.  If configuration is provided directly to the hacluster charm, this
will be preferred over these relation options from the principle charm.

## Resource Configuration

The hacluster interface provides support for a number of different ways
of configuring cluster resources. All examples are provided in python.

NOTE: The hacluster charm interprets the data provided as python dicts; so
it is also possible to provide these as literal strings from charms written
in other languages.

### init\_services

Services which will be managed by pacemaker once the cluster is created:

    init_services = {
            'res_mysqld':'mysql',
        }

These services will be stopped prior to configuring the cluster.

### resources

Resources are the basic cluster resources that will be managed by pacemaker.
In the mysql charm, this includes a block device, the filesystem, a virtual
IP address and the mysql service itself:

    resources = {
        'res_mysql_rbd':'ocf:ceph:rbd',
        'res_mysql_fs':'ocf:heartbeat:Filesystem',
        'res_mysql_vip':'ocf:heartbeat:IPaddr2',
        'res_mysqld':'upstart:mysql',
        }

### resource\_params

Parameters which should be used when configuring the resources specified:

    resource_params = {
        'res_mysql_rbd':'params name="%s" pool="images" user="%s" secret="%s"' % \
                        (config['rbd-name'], SERVICE_NAME, KEYFILE),
        'res_mysql_fs':'params device="/dev/rbd/images/%s" directory="%s" '
                       'fstype="ext4" op start start-delay="10s"' % \
                        (config['rbd-name'], DATA_SRC_DST),
        'res_mysql_vip':'params ip="%s" cidr_netmask="%s" nic="%s"' %\
                        (config['vip'], config['vip_cidr'], config['vip_iface']),
        'res_mysqld':'op start start-delay="5s" op monitor interval="5s"',
        }

### groups

Resources which should be managed as a single set of resource on the same service
unit:

    groups = {
        'grp_mysql':'res_mysql_rbd res_mysql_fs res_mysql_vip res_mysqld',
        }


### clones

Resources which should run on every service unit participating in the cluster:

    clones = {
        'cl_haproxy': 'res_haproxy_lsb'
        }
