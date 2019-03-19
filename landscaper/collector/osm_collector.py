# Copyright (c) 2017, Intel Research and Development Ireland Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
OSM collector.
"""
import time
from osmclient.sol005.client import Client

from landscaper.collector import base
from landscaper.common import LOG
from landscaper import common
from landscaper.utilities import configuration

CONFIGURATION_SECTION='osm'
IDEN_ATTR = {'layer': 'service', 'type': 'stack', 'category': 'compute'}
STATE_ATTR = {'stack_name': None, 'template': None}

# Events to listen for.
ADD_VM_EVENTS = ['compute.instance.create.end',
              'compute.instance.update']
DELETE_VM_EVENTS = ['compute.instance.delete.end',
                 'compute.instance.shutdown.end']

class OSMCollectorV1(base.Collector):
    def __init__(self, graph_db, conf_manager, events_manager, events=None):
        events = ADD_VM_EVENTS + DELETE_VM_EVENTS
        events = events or []
        super(OSMCollectorV1, self).__init__(graph_db, conf_manager, events_manager, events)
        self.conf_mgr=conf_manager
        self.conf_mgr.add_section(CONFIGURATION_SECTION)
        self.osm_host = self.conf_mgr.get_variable(CONFIGURATION_SECTION, "host")
        self.osm_port = self.conf_mgr.get_variable(CONFIGURATION_SECTION, "port")
        self.osm_sol005 = self.conf_mgr.get_variable(CONFIGURATION_SECTION, "sol005")
        self.client = Client(host=self.osm_host, port=self.osm_port)

    def init_graph_db(self):
        """
        1.Get list of VMs from Landscape
        2.Get list of NSs from OSM
        3.Add each of the NS to Landscape if it is running on the VMs in the landscape
        """
        LOG.info("[OSM] Adding OSM components to the landscape.")
        ls_vms = self.get_landscape_VMs()
        ns_list = self.client.ns.list()
        # print ns_list
        now_ts = time.time()
        for ns in ns_list:
            # print self.client.ns.get(ns['id'])
            # if ns['operational-status'] == 'running':
            # print ns
            self._add_service(ns, ls_vms, now_ts)

    def update_graph_db(self, event, body):
        """
        Updates instances.  This method is called by the events manager.
        :param event: The event that has occurred.
        :param body: The details of the event that occurred.
        """
        LOG.info("[OSM] Processing event received: %s", event)
        now_ts = time.time()
        self._process_event(now_ts, event, body)
        LOG.info("EVENT PROCESSED")

    def _process_event(self, timestamp, event, body):
        """
        Process the event based on the type of event.  The event details are
        extracted from the event body.
        :param timestamp: Epoch timestamp.
        :param event: The type of event.
        :param body: THe Event data.
        """
        default = "UNDEFINED"
        payload = body.get("payload", dict())
        uuid = payload.get("instance_id", default)
        print payload
        if event in ADD_VM_EVENTS:
            self._add_vm_services(uuid, timestamp)
        elif event in DELETE_VM_EVENTS:
            self._delete_vm_services(uuid, timestamp)

    def get_landscape_VMs(self):
        """
        Gets all the VMs in the landscape
        :return - A dictionary with VM nodes as values and VM IDs as keys
        """
        props = {"type": "vm"}
        VMs = self.graph_db.get_nodes_by_properties(props)
        vm_dict=dict()
        for VM in VMs:
            VM_ID=VM['name']
            vm_dict[VM_ID]=VM
        return vm_dict

    def _add_service(self, ns, VMs, ts):
        """
        Adds a OSM NS node to the landscape if it is not already there. Also
        connects the OSM NS to the VMs the NS is deployed on.
        :param ns: OSM NS object.
        :param VMs: dictionary with VMs in landscape.
        :param ts: timestamp.
        """
        vims = self.get_ns_vms(ns)
        valid_vms = []
        vnfd_ids = []
        print "In Add Service"
        print "VIMS - {}".format(vims)
        print "VMs - {}".format(VMs)
        print "NS - {}".format(ns)

        for vim_id, vnfd_id in vims:
            print "In Add Service VIM ID loop"
            VM=VMs.get(vim_id)
            # Add the service to landscape as it is running on a VM that is part of landscape
            if VM:
                print "In Add Service valid VM branch"
                valid_vms.append(VM)
                vnfd_ids.append(vnfd_id)
        if len(valid_vms) > 0:
            print "In Add Service LEN(VM) > 0 branch"
            uuid = ns['id']
            osm_node = self.graph_db.get_node_by_uuid(uuid)
            name = ns['name']
            if not osm_node:
                print "In Add Service - Node doesn't exist branch"
                identity, state = self._create_osm_service_nodes(ns)
                LOG.info("Adding OSM NS - : {}".format(name))
                osm_node = self.graph_db.add_node(uuid, identity, state, ts)
            if osm_node is not None:
                print "In Add Service - Node exists branch"
                for i in range(len(valid_vms)):
                    VM = valid_vms[i]
                    vnfd_id = vnfd_ids[i]
                    LOG.info("Adding Edge OSM NS {} -[RUNS ON]- VM {}".format(name, VM['name']))
                    self.graph_db.add_edge(osm_node, VM, ts, "RUNS_ON")
                    self.graph_db.update_node(VM['name'], ts, None, {"osm_vnfd_id": vnfd_id})
            gr = self.graph_db.get_subgraph(uuid)
            print gr

    def _delete_service(self, ns, timestamp):
        """
        Deletes an osm service from the graph database.
        :param ns: OSM NS object.
        :param timestamp: epoch timestamp.
        """
        print "In Delete Service "
        uuid = ns['id']
        name = ns['name']
        service_node = self.graph_db.get_node_by_uuid(uuid)
        if service_node:
            LOG.info("Deleting OSM NS - : {}".format(name))
            self.graph_db.delete_node(service_node, timestamp)


    def _add_vm_services(self, uuid, ts):
        print "In Add VM Services"
        ls_vms = self.get_landscape_VMs()
        vm = ls_vms.get(uuid)
        if not vm:
            return
        print "In Add VM Services step2"
        ns_list = self.client.ns.list()
        ls_vms = dict()
        ls_vms[uuid] = vm
        now_ts = time.time()
        for ns in ns_list:
            print "In Add VM Services NS Loop"
            # if ns['operational-status'] == 'running':
            self._add_service(ns, ls_vms, ts)

    def _delete_vm_services(self, uuid, ts):
        print "In Delete VM Services"
        ns_list = self.client.ns.list()
        for ns in ns_list:
            print "In Delete VM Services NS Loop"
            ns_id = ns['id']
            vims = self.get_ns_vms(ns)
            for vim_id, vnfd_id in vims:
                print "In Delete VM Services VIM Loop"
                if vim_id == uuid:
                    print "In Delete VM Services ID Match Branch - {} & {}".format(vim_id, uuid)
                    ns_node = self._delete_service_from_vm(ns_id, uuid, ts)
                    pred = self.graph_db.predecessors(ns_node)
                    succ = self.graph_db.successors(ns_node)
                    print len(pred)
                    print len(succ)
                    if len(pred) == 0 and len(succ) == 0:
                        print "In Delete VM Services Delete Service Call branch"
                        self._delete_service(ns, ts)
            # gr = self.graph_db.get_subgraph(ns_id)


    # create a node for the service
    def _create_osm_service_nodes(self, ns):
        """
        Creates the identity and state nodes for a OSM service.
        :param ns: OSM NS object.
        :return: Identity and state node.
        """
        identity = IDEN_ATTR.copy()
        state = STATE_ATTR.copy()
        state['service_name'] = ns['name']
        state['template'] = ns['nsd']
        for k in ns:
            if k not in ['nsd', 'name']:
                state[k] = ns[k]
        return identity, state

    def _delete_service_from_vm(self, ns_id, vm_id, ts):
        print "In Delete_SERVICE_FROM_VM "
        ns_node = self.graph_db.get_node_by_uuid(ns_id)
        print ns_node
        vm_node = self.graph_db.get_node_by_uuid(vm_id)
        print vm_node
        if ns_node and vm_node:
            print "In Delete_SERVICE_FROM_VM delete edge branch "
            self.graph_db.delete_edge(ns_node, vm_node, ts)
        return ns_node

    def get_ns_vms(self, ns):
        vms = []
        vnflst = ns.get('constituent-vnfr-ref')
        print "get_ns_vms - vnflst : {}".format(vnflst)
        for vnf_id in vnflst:
            vnf = self.client.vnf.get(vnf_id)
            vims = vnf['vdur']
            vnfd_id = vnf['vnfd-id']
            print "get_ns_vms - vims : {}".format(vims)
            for vim in vims:
                vim_id = None
                try:
                    vim_id = vim['vim-id']
                except:
                    if isinstance(vim, str):
                        vim_id = vim
                if vim_id:
                    vms.append((vim_id, vnfd_id))
        print vms
        return vms
