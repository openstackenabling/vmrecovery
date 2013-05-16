#
#    Copyright (C) 2013 Intel Corporation.  All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import commands
from xml.etree import ElementTree
from nova import context
from nova import utils
from nova.openstack.common import timeutils
from nova import db
from nova import flags
from nova.recover import rpcapi
from nova.openstack.common import log as logging
import socket

LOG = logging.getLogger(__name__)
topic = 'recover'
instance_path = '/var/lib/nova/instances/'
FLAGS = flags.FLAGS

class RecoverDriver(object):
    # number of revoeration of vm
    revcover_num = 0
    dead_hosts = []

    def __init__(self):
        self.recover_rpcapi = rpcapi.RecoverAPI()

    def monitor_host(self, context):
        current_dead_hosts, current_alive_hosts = self._get_dead_hosts(context)

        for host in current_dead_hosts:
            if host in self.dead_hosts:
                current_dead_hosts.remove(host)
            else:
                self.dead_hosts.append(host)

        [self.dead_hosts.remove(host) for host in self.dead_hosts if host in current_alive_hosts]

        for host in current_dead_hosts:
            dead_instances = self._get_dead_instances_by_host(context, host)
            for dead_instance in dead_instances:
                dead_instance_uuid = dead_instance['uuid']
                dead_instance_name = dead_instance['name']
                port_id, port_mac = self._get_port_id_and_mac_by_vm_uuid(context, dead_instance_uuid)
                scheduler_host = self._scheduler_host(context, current_alive_hosts)
                self.recover_rpcapi.recover_vm(context, scheduler_host, port_id, port_mac, dead_instance_uuid,
                    dead_instance_name)


    def recover_vm(self, context, vm_name, vm_uuid, port_id, port_mac):
        LOG.debug('recover_vm start')
        self._recover_net(port_id, port_mac, vm_uuid)
        self._update_libvirt(vm_name)
        self._recover_vm_instance(vm_name)
        self.update_instance_in_db(context, vm_uuid, socket.gethostname())
        LOG.debug('recover_vm end')

    def update_instance_in_db(self, context, vm_uuid, dest_host):
        LOG.debug('update_instance_in_db start')
        db.instance_update(context, vm_uuid, {'host': dest_host, 'launched_on': dest_host})
        LOG.debug('update_instance_in_db end')


    def _update_libvirt(self, vm_name):
        LOG.debug('_update_libvirt start')
        libvirt_path = instance_path + '%s/libvirt.xml' % vm_name
        cmm = 'sudo chmod 666 %s' % libvirt_path
        commands.getstatusoutput(cmm)
        self._clear_tag_from_xml(libvirt_path, 'filterref')
        LOG.debug('_update_libvirt end')


    def _clear_tag_from_xml(self, file_path, tag):
        root = ElementTree.parse(file_path)

        list_nodes = root.iter(tag)

        for node in list_nodes:
            node.clear()

        root.write(file_path)


    def _recover_net(self, port_id, port_mac, vm_uuid):
        LOG.debug('_recover_net start')
        sub_port_id = port_id[:11]

        shell_commands = (
            'sudo brctl addbr qbr%s' % sub_port_id,
            'sudo ip link add qvb%s type veth peer name qvo%s' % (sub_port_id, sub_port_id),
            'sudo ip link set qvb%s up' % sub_port_id,
            'sudo ip link set qvo%s up' % sub_port_id,
            'sudo ip link set qvb%s promisc on' % sub_port_id,
            'sudo ip link set qvo%s promisc on' % sub_port_id,
            'sudo ip link set qbr%s up' % sub_port_id,
            'sudo brctl addif qbr%s qvb%s' % (sub_port_id, sub_port_id),
            'sudo ovs-vsctl -- --may-exist add-port br-int qvo%s -- set Interface qvo%s  external-ids:iface-id=%s  external-ids:iface-status=active  external-ids:attached-mac=%s  external-ids:vm-uuid=%s' % (
            sub_port_id, sub_port_id, port_id, port_mac, vm_uuid)
            )

        for value in shell_commands:
            status, output = commands.getstatusoutput(value)

        LOG.debug('_recover_net end')

    def _recover_vm_instance(self, vm_name):
        LOG.debug('_recover_vm_instance start')
        shell_commands = (
            'sudo virsh define /var/lib/nova/instances/%s/libvirt.xml' % vm_name,
            'sudo virsh start %s' % vm_name,
            )

        for value in shell_commands:
            status, output = commands.getstatusoutput(value)

        LOG.debug('_recover_vm_instance end')


    def _get_dead_hosts(self, context):
        '''
        get the node status by nova-recover service
        and return all failed node
        :param context:
        :return:
        '''
        now = timeutils.utcnow()
        services = db.service_get_all_by_topic(context, topic)
        dead_hosts = []
        alive_hosts = []
        for service in services:
            delta = now - (service['updated_at'] or service['created_at'])
            alive = abs(utils.total_seconds(delta)) <= FLAGS.service_down_time
            service_host = service['host']
            if  alive:
                alive_hosts.append(service_host)
            else:
                dead_hosts.append(service_host)
        return dead_hosts, alive_hosts


    def _get_dead_instances_by_host(self, context, host):
        return db.instance_get_all_by_host(context, host)


    def _get_port_id_and_mac_by_vm_uuid(self, context, vm_uuid):
        instance_info_cache = db.instance_info_cache_get(context, vm_uuid)
        mac_length = 17
        uuid_length = 36

        start = instance_info_cache.network_info.rfind('address') + 11
        end = start + mac_length
        mac = instance_info_cache.network_info[start: end]

        start = instance_info_cache.network_info.rfind('id') + 6
        end = start + uuid_length
        port_id = instance_info_cache.network_info[start: end]

        #        lambda a, b, c ,d :  a[a.rfind(b) + c : a.rfind(b) + c + d]

        return port_id, mac

    def _scheduler_host(self, context, alive_hosts):
        # get a host from alive_hosts list, to recover the vm
        if len(alive_hosts) == 0:
            raise Exception('no mova alive host for recover')

        compute_services = db.service_get_all_by_topic(context, 'compute')
        compute_hosts = []
        for service in compute_services:
            compute_hosts.append(service['host'])
        while True:
            index = self.revcover_num % len(alive_hosts)
            self.revcover_num += 1
            if alive_hosts[index] in compute_hosts:
                return alive_hosts[index]




