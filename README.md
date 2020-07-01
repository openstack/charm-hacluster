# Overview

The hacluster charm provides high availability for OpenStack applications that
lack native (built-in) HA functionality. The clustering solution is based on
Corosync and Pacemaker.

It is a subordinate charm that works in conjunction with a principle charm that
supports the 'hacluster' interface. The current list of such charms can be
obtained from the [Charm Store][charms-requires-hacluster] (the charms
officially supported by the OpenStack Charms project are published by
'openstack-charmers').

See [OpenStack high availability][cdg-ha] in the [OpenStack Charms Deployment
Guide][cdg] for a comprehensive treatment of HA with charmed OpenStack.

> **Note**: The hacluster charm is generally intended to be used with
  MAAS-based clouds.

# Usage

High availability can be configured in two mutually exclusive ways:

* virtual IP(s)
* DNS

The virtual IP method of implementing HA requires that all units of the
clustered OpenStack application are on the same subnet.

The DNS method of implementing HA requires that [MAAS][upstream-maas] is used
as the backing cloud. The clustered nodes must have static or "reserved" IP
addresses registered in MAAS. If using a version of MAAS earlier than 2.3 the
DNS hostname(s) should be pre-registered in MAAS before use with DNS HA.

## Configuration

This section covers common configuration options. See file `config.yaml` for
the full list of options, along with their descriptions and default values.

#### `cluster_count`

The `cluster_count` option sets the number of hacluster units required to form
the principle application cluster (the default is 3). It is best practice to
provide a value explicitly as doing so ensures that the hacluster charm will
wait until all relations are made to the principle application before building
the Corosync/Pacemaker cluster, thereby avoiding a race condition.

## Deployment

At deploy time an application name should be set, and be based on the principle
charm name (for organisational purposes):

    juju deploy hacluster <principle-charm-name>-hacluster

A relation is then added between the hacluster application and the principle
application.

In the below example the VIP approach is taken. These commands will deploy a
three-node Keystone HA cluster, with a VIP of 10.246.114.11. Each will reside
in a container on existing machines 0, 1, and 2:

    juju deploy -n 3 --to lxd:0,lxd:1,lxd:2 --config vip=10.246.114.11 keystone
    juju deploy --config cluster_count=3 hacluster keystone-hacluster
    juju add-relation keystone-hacluster:ha keystone:ha

## Actions

This section lists Juju [actions][juju-docs-actions] supported by the charm.
Actions allow specific operations to be performed on a per-unit basis.

 * `pause`
 * `resume`
 * `status`
 * `cleanup`
 * `update-ring`

To display action descriptions run `juju actions hacluster`. If the charm is
not deployed then see file ``actions.yaml``.

### update-ring action

The `update-ring` action requires a parameter (`i-really-mean-it=true`) to make
sure tidying up the list of available corosync nodes in the ring is intended.

The operation expects:

1. `juju run-action hacluster/N pause --wait`. This will make sure no Pacemaker
   resources run on the unit.

2. `juju remove-unit principal-unit/N`. Iterate through this step as many times
   as units want to be removed (ie. to scale back from 6 to 3 units).

3. `juju run-action hacluster/leader update-ring i-really-mean-it=true --wait`.
   This step will remove corosync nodes from the ring and update corosync.conf
   to list an updated number of nodes (min_quorum is recalculated).

In case a unit goes into lost state (ie. caused by hardware failure), the
initial step (pause a unit) can be skipped. Unit removal may also be replaced
by `juju remove-machine N --force`, where N is the Juju machine ID where the
unit to be removed runs.

# Bugs

Please report bugs on [Launchpad][lp-bugs-charm-hacluster].

For general charm questions refer to the [OpenStack Charm Guide][cg].

<!-- LINKS -->

[cg]: https://docs.openstack.org/charm-guide
[lp-bugs-charm-hacluster]: https://bugs.launchpad.net/charm-hacluster/+filebug
[juju-docs-actions]: https://jaas.ai/docs/actions
[cdg-ha]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/app-ha.html
[upstream-maas]: https://maas.io
[charms-requires-hacluster]: https://jaas.ai/search?requires=hacluster
[cdg]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide
