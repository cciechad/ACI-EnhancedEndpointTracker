
from ... rest import Rest
from ... rest import api_register
from ... rest import api_callback
from .. utils import get_parent_dn
from . import ManagedObject

import logging

# module level logging
logger = logging.getLogger(__name__)

@api_register(parent="fabric", path="mo/mgmtRsMgmtBD")
class mgmtRsMgmtBD(ManagedObject):

    META = ManagedObject.append_meta({
        "tDn": {},
        "parent": {
            "type": str,
            "description": "parent mgmtInB dn for this object"
        },
    })

    @staticmethod
    @api_callback("before_create")
    def before_create(data):
        """ set parent to mgmtInB based on dn """
        data["parent"] = get_parent_dn(data["dn"])
        return data
