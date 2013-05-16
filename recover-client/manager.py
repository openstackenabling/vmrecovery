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

from nova import db
from nova import flags
from nova import manager
from nova.openstack.common import cfg
from nova.openstack.common import importutils
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)

scheduler_driver_opt = cfg.StrOpt('recover_driver',
    default='nova.recover.driver.RecoverDriver',
    help='Default driver to use for the recover')

FLAGS = flags.FLAGS
FLAGS.register_opt(scheduler_driver_opt)

LOG = logging.getLogger(__name__)
topic = 'recover'

class RecoverManager(manager.Manager):

    RPC_API_VERSION = "1.0"

    def __init__(self, driver=None, *args, **kwargs):
        if not driver:
            driver = FLAGS.recover_driver
        self.driver = importutils.import_object(driver)
        super(RecoverManager, self).__init__(*args, **kwargs)


    def recover_vm(self, context, port_id, port_mac, vm_uuid, vm_name):
        """
        Recover vm net by quantum service ,and vm by libvirt
        :param context:
        :param port_id:
        :param port_mac:
        :param vm_uuid:
        :param vm_name:
        :return:
        """
        self.driver.recover_vm(context, vm_name, vm_uuid, port_id, port_mac)
