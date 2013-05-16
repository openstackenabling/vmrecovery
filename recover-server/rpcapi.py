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

from nova import exception
from nova import flags
from nova.openstack.common import rpc
from nova.openstack.common.rpc.proxy import RpcProxy
from nova.openstack.common import log as logging
from nova.openstack.common import cfg

recover_topic_opt = cfg.StrOpt('recover_topic', default = 'recover', help='')


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS
FLAGS.register_opt(recover_topic_opt)

def _recover_topic(topic, ctxt, host, instance):
    '''Get the topic to use for a message.

    :param topic: the base topic
    :param ctxt: request context
    :param host: explicit host to send the message to.
    :param instance: If an explicit host was not specified, use
                     instance['host']

    :returns: A topic string
    '''
    if not host:
        if not instance:
            raise exception.NovaException(_('No recover host specified'))
        host = instance['host']
    if not host:
        raise exception.NovaException(_('Unable to find host for '
                                        'Instance %s') % instance['uuid'])
    return rpc.queue_get_for(ctxt, topic, host)

class RecoverAPI(RpcProxy):

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self):
        super(RecoverAPI, self).__init__(topic=FLAGS.recover_topic, default_version=self.BASE_RPC_API_VERSION)

    def recover_vm(self, context,scheduler_host, port_id, port_mac, vm_uuid, vm_name):
        return self.cast(
                        context,
                        self.make_msg('recover_vm', port_id=port_id, port_mac=port_mac, vm_uuid=vm_uuid, vm_name=vm_name),
                        topic = _recover_topic(self.topic, context, scheduler_host, None),
                        version = '1.0'
        )

