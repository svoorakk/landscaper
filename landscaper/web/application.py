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
REST Application for the landscape.
"""
import ast
import time

import json
import flask
from flask import request
from flask import Response
from flask import abort
from flask_cors import CORS

from landscaper.common import LOG
from landscaper import landscape_manager as lm
from landscaper.utilities.coordinates import Geo


APP = flask.Flask(__name__)
CORS(APP)

LANDSCAPE = None
MIME = "application/json"


@APP.route("/graph")
def get_graph():
    """
    Returns the full landscape graph as node-link json.
    """
    LOG.info("Retrieving Landscape with url : %s", request.url)
    geo = _boolean(request.args.get("geo", False))
    graph = LANDSCAPE.graph_db.get_graph()
    if geo:
        graph = Geo.extract_geo(graph)
    return Response(graph, mimetype=MIME)


@APP.route("/subgraph/<node_id>")
def get_subgraph(node_id):
    """
    Returns the subgraph using a node id as the start.
    """
    LOG.info("Retrieving Subgraph with url %s", request.url)
    timestamp = request.args.get("timestamp")
    time_frame = request.args.get("timeframe", 0)
    geo = _boolean(request.args.get("geo", False))
    subgraph = LANDSCAPE.graph_db.get_subgraph(node_id, timestmp=timestamp,
                                               timeframe=time_frame)
    if not subgraph:
        err_msg = "Node with ID '{}', not in the landscape.".format(node_id)
        LOG.error(err_msg)
        abort(400, err_msg)

    if geo:
        subgraph = Geo.extract_geo(subgraph)

    return Response(subgraph, mimetype=MIME)


@APP.route("/node/<node_id>")
def get_node_by_uuid(node_id):
    """
    Returns a networkx graph containing the node.
    """
    LOG.info("Retrieving node by uuid, with url %s", request.url)
    geo = _boolean(request.args.get("geo", False))
    graph = LANDSCAPE.graph_db.get_node_by_uuid_web(node_id)

    if not graph:
        err_msg = "Node with ID '{}', not in the landscape.".format(node_id)
        LOG.error(err_msg)
        abort(400, err_msg)

    if geo:
        graph = Geo.extract_geo(graph)

    return Response(graph, mimetype=MIME)


@APP.route("/nodes")
def get_node_by_properties():
    """
    Returns a graph containing just the nodes that match the properties.
    """
    LOG.info("Retrieving node by props with url %s", request.url)
    timestamp = request.args.get("timestamp") or time.time()
    time_frame = request.args.get("timeframe", 0)
    properies_string = request.args.get("properties")
    if not properies_string:
        err_msg = "Properties must be specified."
        LOG.warn(err_msg)
        abort(400, err_msg)
    properties = ast.literal_eval(properies_string)
    graph = LANDSCAPE.graph_db.get_node_by_properties_web(properties,
                                                          timestamp,
                                                          time_frame)
    return Response(graph, mimetype=MIME)


@APP.route("/coordinates", methods=['PUT'])
def put_geolocation():
    """
    Stores the geolocation of the nodes to the database
    """
    LOG.info("Accessing URL %s", request.url)
    now_ts = time.time()
    error_log = []
    if not request.data:
        err_msg = "No coordinate data"
        abort(400, err_msg)

    data = ast.literal_eval(request.data)

    for obj in data:
        LOG.info("Updating coordinates of nodes %s", obj['id'])
        geo_string = json.dumps(obj['geo'])
        attrs = {"geo": geo_string}
        updated, msg = LANDSCAPE.graph_db.update_node(obj['id'], now_ts,
                                                      extra_attrs=attrs)
        if not updated:
            error_log.append((obj["id"], msg))

    if error_log:
        err_msg = "Error with the following nodes:" + str(error_log)
        abort(400, err_msg)

    return Response(status=200, mimetype=MIME)


def _boolean(value):
    """
    Determine if the bool value supplied can be interpreted as bool.
    :param value: boolean value
    :return: True / False
    """
    if not value:
        return False
    if isinstance(value, bool):
        return value

    # if the value is any other simple type.
    value = str(value).lower().strip()
    if value in ('true', '1',):
        return True
    if value in ('false', '0',):
        return False

    return False


@APP.before_first_request
def initilise_application():
    """
    Setup the application before it is run.
    """
    global LANDSCAPE
    if not LANDSCAPE:
        LANDSCAPE = lm.LandscapeManager()