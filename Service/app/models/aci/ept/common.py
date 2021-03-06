"""
common ept functions
"""
from . ept_msg import MSG_TYPE
from . ept_msg import eptMsg

import logging
import os
import re
import threading
import time
import traceback

# module level logging
logger = logging.getLogger(__name__)

###############################################################################
#
# shared globals
#
###############################################################################

# dynamic imports of MOs need base relatively to full project
MO_BASE                             = "app.models.aci.mo"
# minimum version of supported code (2.2.1n)
MINIMUM_SUPPORTED_VERSION           = "2.2.1n"

HELLO_INTERVAL                      = 5.0
HELLO_TIMEOUT                       = 60.0
WATCH_INTERVAL                      = 1.0
NOTIFY_INTERVAL                     = 1.0
NOTIFY_QUEUE_MAX_SIZE               = 4096
CACHE_STATS_INTERVAL                = 300.0
SEQUENCE_TIMEOUT                    = 100.0
MANAGER_CTRL_CHANNEL                = "mctrl"
MANAGER_CTRL_RESPONSE_CHANNEL       = "r_mctrl"
MANAGER_WORK_QUEUE                  = "mq"
SUBSCRIBER_CTRL_CHANNEL             = "sctrl"
WORKER_CTRL_CHANNEL                 = "wctrl"
WORKER_UPDATE_INTERVAL              = 15.0
RAPID_CALCULATE_INTERVAL            = 15.0
MAX_SEND_MSG_LENGTH                 = 10240
BG_EVENT_HANDLER_INTERVAL           = 0.01
BG_EVENT_HANDLER_ENABLED            = True

# when API requests msg queue length, manager can read the full data off each queue and accurate
# msgs within bulk messages for accurate count. There is a performance hit to this so the
# alternative is counting the number of messages in each queue where a bulk message counts as one.
ACCURATE_QUEUE_LENGTH               = False

# transitory timers:
#   max_epm_build   maximum amount of time to wait for ACK from all worker processes to indiciate
#                   that all initial epm messages (from build created/delete) have been processed.
#                   when exceeded, warning is logged to fabric events and watcher is unpaused.
#   uptime          amount of time added to all transitory events when fabric is first started. For
#                   example, if the uptime of the fabric subscription is 100 seconds and transitory
#                   uptime is 300, then an additional 200 seconds needs to be added to any transitory
#                   event before they are triggered.  This allows additionally buffer during start
#                   up for large scale.
#   delete          amount of time between delete and create events to treat as a change/move
#   offsubnet       amount of time to wait before declaring endpoint is learned offsubnet
#   stale           amount of time to wait for new events before declaring endpoint is stale
#   stale_no_local  amount of time to wait for new events when an endpoint is declared as stale
#                   and there is no local endpoint learned within the fabric (i.e., expected remote
#                   node is 0)
#   rapid           amount of time to wait for new events when an endpoint is is_rapid is cleared
#                   note, watcher execute time is delayed for rapid_holdtime + transitory_rapid
#                   timer to wait and see if endpoint is flagged as rapid a second time before 
#                   restore_rapid action is applied.  This time should be greater than
#                   RAPID_CALCULATE_INTERVAL
#   
# suppress timers
#   watch_offsubnet amount of time to suppress new watch_offsubnet events for single node/ep
#   watch_stale     amount of time to suppress new watch_stale events for single node/ep
#   fabric_restart  amount of time to suppress new fabric monitor restart events
MAX_EPM_BUILD_TIME                  = 5400.0
TRANSITORY_UPTIME                   = 900.0 
TRANSITORY_DELETE                   = 60.0
TRANSITORY_OFFSUBNET                = 10.0
TRANSITORY_STALE                    = 45.0
TRANSITORY_STALE_NO_LOCAL           = 315.0
TRANSITORY_RAPID                    = 35.0
SUPPRESS_WATCH_OFFSUBNET            = 8.0
SUPPRESS_WATCH_STALE                = 25.0
SUPPRESS_FABRIC_RESTART             = 60.0

###############################################################################
#
# common attribute names for ept event objects
#
###############################################################################

common_event_attribute = {
    "classname": {
        "type": str,
        "description": "epm classname that triggered the event"
    },
    "ts": {
        "type": float,
        "description": "epoch timestamp the event was detected",
    },
    "status": {
        "type": str,
        "description": "current status of the endpoint (created, modified, deleted)",
        "values": ["created", "modified", "deleted"],
    },
    "remote": {
        "type": int,
        "description": """
        resolved tunnel to node id for remote learns. Note, this may be an emulated
        node-id representing a vpc pair.  See eptNode object for more details
        """
    },
    "pctag": {
        "type": int,
        "description": """
        policy control tag representing epg.  For epgs with pctag of 'any', this is
        programmed with a value of 0
        """,
    },
    "flags": {
        "type": list,
        "subtype": str,
        "description": "epm flags for endpoint event",
    },
    "tunnel_flags": {
        "type": str,
        "description": """ interface flags if intf_id is a tunnel """,
    },
    "encap": {
        "type": str,
        "description": "vlan or vxlan encap for local learn",
    },
    "intf_id": {
        "type": str,
        "description": "interface id where endpoint was learned",
    },
    "intf_name": {
        "type": str,
        "description": """
        interface name. This is only relevant for port-channels, all interface types
        should have identical intf_id and intf_name
        """,
    },
    "rw_mac": {
        "type": str,
        "description": """
        rewrite mac address for local ipv4/ipv6 endpoints.
        """,
    },
    "rw_bd": {
        "type": int,
        "description": """
        BD VNID for mac of local ipv4/ipv6 endpoints.  This is 0 if not known.
        """,
    },
    "epg_name": {
        "type": str,
        "description": "epg name based on vrf and pctag at the time of this event",
    },
    "vnid_name": {
        "type": str,
        "description": "vnid name based on at the time of this event",
    }
}


###############################################################################
#
# initializing functions
#
###############################################################################

def wait_for_redis(redis_db, check_interval=1):
    """ blocking function that waits until provided redis-db is available """
    while not redis_alive(redis_db):
        if check_interval > 0:
            time.sleep(check_interval)
        else:
            return

def redis_alive(redis_db):
    """ return boolean if redis db is alive """
    try:
        if redis_db.dbsize() >= 0:
            #logger.debug("redis_alive successfully connected to redis db")
            return True
    except Exception as e:
        logger.debug("failed to connect to redis db: %s", e)
        return False

def wait_for_db(db, check_interval=1):
    """ blocking function that waits until provided mongo-db is available """
    while not db_alive(db):
        if check_interval > 0:
            time.sleep(check_interval)
        else:
            return

def db_alive(db):
    """ return boolean if db is alive """
    try:
        if len(db.collection_names()) >= 0:
            #logger.debug("db_alive successfully connected to mongo db")
            return True
    except Exception as e:
        logger.debug("failed to connect to mongo db: %s", e)
        return False

def get_queue_length(rdb, queue, accurate=True):
    """ get number of pending messages in queue. Requires an active connection to redis and the name
        of the queue to collect message length. Set accurate to true to inspect each message 
        individually and include sub-messages from eptBulk.  Note, ACCURATE_QUEUE_LENGTH must be 
        enabled as well.
    """
    if accurate and ACCURATE_QUEUE_LENGTH:
        # to support accurate message count for eptMsgBulk, we need to inspect each message
        # we may revisit this at a later time but for now, we will use lrange to pull all messages 
        # and count them and any sub-messages.
        count = 0
        for data in rdb.lrange(queue, 0, -1):
            # need to reparse message and check fabric
            msg = eptMsg.parse(data, brief=True) 
            if msg.msg_type == MSG_TYPE.BULK:
                count+= msg.msg_count
            else:
                count+=1
        return count
    else:
        return rdb.llen(queue) 

###############################################################################
#
# ept specific functions
#
###############################################################################

def get_vpc_domain_id(n1, n2):
    """ calculate interger vpc_domain_id for two node ids
        id is always (lower node id) << 16 + (higher node id)
    """
    n1 = int(n1)
    n2 = int(n2)
    if n1 > n2: return (n2 << 16) + n1
    return (n1 << 16) + n2

def get_vpc_domain_name(n):
    """ receives a node id and returns str value.  If a vpc domain then string is in form (n1,2) """
    (n1, n2) = split_vpc_domain_id(n)
    if n1 > 0 and n2 > 0:
        return "(%s,%s)" % (n1, n2)
    return "%s" % n

def split_vpc_domain_id(n):
    """ receives node id and split to member node ids. Note, if domain id is invalid then result 
        can contain node values of 0
        returns list of length 2 (node1, node2)
    """
    return [(n & 0xffff0000)>>16, n & 0x0000ffff]

def push_event(collection, key, event, rotate=None, increment=True):
    """ push an event into the events list of a collection. If increment is true, then increment
        the 'count' attribute of the object.
        return bool success
    """
    update = {"$push": {"events": {"$each": [event], "$position": 0 } } } 
    if rotate is not None:
        update["$push"]["events"]["$slice"] = rotate
    if increment:
        update["$inc"] = {"count": 1}
    # logger.debug("push event key: %s, event:%s", key, event)
    r = collection.update_one(key, update, upsert=True)
    # to support disabling write concern, we can only check for a successfull push if ack is enabled
    if collection.client.write_concern.acknowledged:
        if r.matched_count == 0:
            if "n" in r.raw_result and "updatedExisting" in r.raw_result and \
                not r.raw_result["updatedExisting"] and r.raw_result["n"]>0:
                # result was upserted (new entry added to db)
                pass
            else:
                logger.warn("failed to push event key:%s, event:%s", key, event)
                return False
    return True

def get_addr_type(addr, addr_type):
    # receive an addr and addr_type (mac or ip) and return a type of mac, ipv4, or ipv6
    if addr_type == "ip":
        if ":" in addr: return "ipv6"
        else: return "ipv4"
    return addr_type

def parse_vrf_name(dn):
    # receive a vrf dn in the form uni/tn-<tenant>/ctx-<ctx>, and return tenant:ctx vrf name
    # return None on error.  Note, this function will fail
    r1 = re.search("^uni/tn-(?P<tn>[^/]+)/ctx-(?P<ctx>.+)$", dn)
    if r1 is not None:
        return "%s:%s" % (r1.group("tn"), r1.group("ctx"))
    elif dn == "uni/tn-infra/ctx-overlay-1":
        return "overlay-1"
    else:
        logger.warn("failed to parse vrf name for dn: %s", dn)
        return None


def subscriber_op(fabric, msg_type, data=None, qnum=1):
    """ send msg to subscriber with provided msg_type and data. The message is only sent if fabric 
        is currently running, else an error is returned.
        returns a tuple (success, error_string)
    """
    from ... utils import get_redis
    from .. fabric import Fabric
    from . ept_msg import eptMsgSubOp

    if data is None: data = {}
    if Fabric(fabric=fabric).get_fabric_status(api=False):
        r = None
        try:
            # fabric and qnum are always in data, add if not present
            data["fabric"] = fabric
            data["qnum"] = qnum
            msg = eptMsgSubOp(msg_type, data = data).jsonify()
            logger.debug("subscriber_op publishing msg: %s", msg)
            r = get_redis()
            r.publish(SUBSCRIBER_CTRL_CHANNEL, msg)
            # no error sending message so assume success
            return (True, "")
        except Exception as e:
            logger.error("Traceback:\n%s", traceback.format_exc())
            return (False, "failed to publish message on redis channel")
        finally:
            if r is not None and hasattr(r, "connection_pool"):
                r.connection_pool.disconnect()
    else:
        return (False, "Fabric '%s' is not running" % fabric)

def parse_tz(tz):
    # expect to be in the form n#_Region-Tz where we need to replace - with /
    r1 = re.search("^n[0-9]+_(?P<region>[^\-]+)-(?P<tz>.+)$", tz)
    if r1 is not None:
        return "%s/%s" % (r1.group("region"), re.sub("-","/", r1.group("tz")))
    else:
        logger.warn("failed to parse timezone: %s", tz)
        return tz

###############################################################################
#
# common conversion functions
#
###############################################################################

def get_mac_string(mac, fmt="dd"):
    """ takes 48-bit (12 character) integer and returns dotted mac 
        formats: 
            dd (dotted-decimal)     xxxx.xxxx.xxxx
            std (standard)          XX:XX:XX:XX:XX:XX
    """
    if fmt == "dd":
        return "{0:04x}.{1:04x}.{2:04x}".format(
            (mac & 0xffff00000000) >> 32,
            (mac & 0xffff0000) >> 16 ,
            mac & 0xffff
        )
    else:
        return "{0:02x}:{1:02x}:{2:02x}:{3:02x}:{4:02x}:{5:02x}".format(
            (mac & 0xff0000000000) >> 40,  
            (mac & 0x00ff00000000) >> 32,  
            (mac & 0x0000ff000000) >> 24,  
            (mac & 0x000000ff0000) >> 16,  
            (mac & 0x00000000ff00) >> 8,  
            (mac & 0x0000000000ff)
        ).upper()

mac_reg = "^(?P<o1>[a-f0-9]{1,4})[.\-:]"
mac_reg+= "(?P<o2>[a-f0-9]{1,4})[.\-:]"
mac_reg+= "(?P<o3>[a-f0-9]{1,4})$"
mac_reg = re.compile(mac_reg, re.IGNORECASE)
def get_mac_value(mac):
    """ takes mac string and returns 48-bit integer. this will support the following formats:
            E                   (single integer in hex format)
            E.E.E
            EE-EE-EE-EE-EE-EE
            EE.EE.EE.EE.EE.EE
            EEEE.EEEE.EEEE
        returns 0 on error
    """
    mac = "%s" % mac
    # either matches mac_reg or able to cast with base 16
    r1 = mac_reg.search(mac)
    if r1 is not None:
        o1 = int(r1.group("o1"),16) << 32
        o2 = int(r1.group("o2"),16) << 16
        o3 = int(r1.group("o3"),16)
        return o1+o2+o3
    try: return int(re.sub("[.\-:]","",mac),16)
    except Exception as e: 
        logger.warn("failed to convert mac '%s' to integer: %s", mac, e)
        return 0

def get_ip_prefix(ip):
    """ receives ipv4 or ipv6 string with or without mask, determines if the address is ipv4 or ipv6,
        then returns result of get_ipv4_prefix or get_ipv6_prefix
    """
    if ":" in ip:
        return get_ipv6_prefix(ip)
    return get_ipv4_prefix(ip)

def get_ipv4_string(ipv4):
    """ takes 32-bit integer and returns dotted ipv4 """
    return "%s.%s.%s.%s" % (
        (ipv4 & 0xff000000) >> 24,
        (ipv4 & 0xff0000) >> 16,
        (ipv4 & 0xff00) >> 8 ,
        ipv4 & 0xff
    )

ipv4_prefix_reg = "^(?P<o0>[0-9]+)\.(?P<o1>[0-9]+)\.(?P<o2>[0-9]+)\."
ipv4_prefix_reg+= "(?P<o3>[0-9]+)(/(?P<m>[0-9]+))?$"
ipv4_prefix_reg = re.compile(ipv4_prefix_reg)
def get_ipv4_prefix(ipv4):
    """ takes ipv4 string with or without prefix present and returns tuple:
            (address, mask) where addr and mask are 32-bit ints
        if no mask is present, the /32 is assumed
        mask is '1-care' format.  For example:
            /0  = 0x00000000
            /8  = 0xff000000
            /16 = 0xffff0000
            /24 = 0xffffff00
            /32 = 0xffffffff
        returns (None,None) on error
    """
    r1 = ipv4_prefix_reg.search(ipv4)
    if r1 is None:
        logger.warn("address %s is invalid ipv4 address", ipv4)
        return (None, None)
    if r1.group("m") is not None: mask = int(r1.group("m"))
    else: mask = 32
    oct0 = int(r1.group("o0"))
    oct1 = int(r1.group("o1"))
    oct2 = int(r1.group("o2"))
    oct3 = int(r1.group("o3"))
    if oct0 > 255 or oct1 > 255 or oct2 > 255 or oct3 > 255 or mask > 32:
        logger.warn("address %s is invalid ipv4 address", ipv4)
        return (None, None)

    addr = (oct0 << 24) + (oct1 << 16) + (oct2 << 8) + oct3
    mask = (~(pow(2,32-mask)-1)) & 0xffffffff
    return (addr&mask, mask)

def get_ipv6_string(ipv6):
    """ takes 64-bit integer and converts to ipv6 """
    s = "%x:%x:%x:%x:%x:%x:%x:%x" % (
        (ipv6 & 0xffff0000000000000000000000000000 ) >> 112,
        (ipv6 & 0x0000ffff000000000000000000000000 ) >> 96,
        (ipv6 & 0x00000000ffff00000000000000000000 ) >> 80,
        (ipv6 & 0x000000000000ffff0000000000000000 ) >> 64,
        (ipv6 & 0x0000000000000000ffff000000000000 ) >> 48,
        (ipv6 & 0x00000000000000000000ffff00000000 ) >> 32,
        (ipv6 & 0x000000000000000000000000ffff0000 ) >> 16,
        (ipv6 & 0x0000000000000000000000000000ffff )
    )
    # ipv6 best practice to replaces multiple 0-octects with ::
    return re.sub(":[0:]+", "::", s, 1)

ipv6_prefix_reg = re.compile("^(?P<addr>[0-9a-f:]{2,40})(/(?P<m>[0-9]+))?$", re.IGNORECASE)
def get_ipv6_prefix(ipv6):
    """ takes ipv6 string with or without prefix present and returns tuple:
            (address, mask) where addr and mask are 128-bit ints
        if no mask is present, the /128 is assumed
        mask is '1-care' format.  For example:
            /0  = 0x00000000 00000000 00000000 00000000
            /24 = 0xffffff00 00000000 00000000 00000000
            /64 = 0xffffffff ffffffff 00000000 00000000
            /128= 0xffffffff ffffffff ffffffff ffffffff
        returns (None,None) on error
    """
    r1 = ipv6_prefix_reg.search(ipv6)
    if r1 is None:
        logger.warn("address %s is invalid ipv6 address", ipv6)
        return (None, None)
    if r1.group("m") is not None: mask = int(r1.group("m"))
    else: mask = 128

    upper = []
    lower = []
    # split on double colon to determine number of double-octects to pad
    dc_split = r1.group("addr").split("::")
    if len(dc_split) == 0 or len(dc_split)>2:
        logger.warn("address %s is invalid ipv6 address", ipv6)
        return (None, None)
    if len(dc_split[0])>0:
        for o in dc_split[0].split(":"): upper.append(int(o,16))
    if len(dc_split)==2 and len(dc_split[1])>0:
        for o in dc_split[1].split(":"): lower.append(int(o,16))
    # ensure there are <=8 total double-octects including pad
    pad = 8 - len(upper) - len(lower)
    if pad < 0 or pad >8:
        logger.warn("address %s is invalid ipv6 address", ipv6)
        return (None, None)

    # sum double-octects with shift
    addr = 0
    for n in (upper + [0]*pad + lower): addr = (addr << 16) + n
    mask = (~(pow(2,128-mask)-1)) & 0xffffffffffffffffffffffffffffffff
    return (addr&mask, mask)


def get_random_sequence():
    # using os.urandom return a pseudo random sequeunce number
    return sum(ord(c)<<4*i for i, c in enumerate(os.urandom(8))) & 0xffffffff


###############################################################################
#
# Basic timer class that repeats function in background thread at regular interval
#
###############################################################################

class BackgroundThread(threading.Thread):
    """ simply background thread that executes provided function with provided args at regular
        interval. Set count to zero to repeat indefinitely at the provided interval (in seconds).
    """
    def __init__(self, func=None, name=None, count=1, interval=1.0, args=None, kwargs=None):
        threading.Thread.__init__(self)
        self._exit = False
        if name is not None:
            self.name = "%s" % name
        self.func = func
        self.max_count = count
        self.count = 0
        self.interval = interval
        self.args = args
        self.kwargs = kwargs
        if self.args is None:
            self.args = []
        if self.kwargs is None:
            self.kwargs = {}
        if not callable(self.func):
            raise Exception("background thread function (%s) not callable" % self.func)

    def exit(self):
        """ exit thread """
        logger.debug("exiting background thread: %s", self.name)
        self._exit = True

    def run(self):
        logger.debug("starting background thread: %s", self.name)
        while not self._exit:
            self.count+=1
            try:
                self.func(*self.args, **self.kwargs)
            except Exception as e:
                logger.debug("Traceback:\n%s", traceback.format_exc())
                logger.error("failed to execute background process: %s", e)
            if self.max_count > 0 and self.count >= self.max_count:
                # stop execution when reaching max number of iterations
                return
            time.sleep(self.interval)

