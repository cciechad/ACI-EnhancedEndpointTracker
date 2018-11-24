
function fabricEvent(){
    baseModelObject.call(this)
    var self = this
    self.timestamp = ko.observable(0)
    self.status = ko.observable("")
    self.description = ko.observable("")
    self.ts_str = ko.computed(function(){
        return timestamp_to_string(self.timestamp())
    }) 

    // custom cell formatting per attribute
    self.formatter = function(attr, text){
        if(attr == "status"){
            var alabel = ""
            switch(text){
                case "running": alabel = "label--success" ; break;
                case "starting":alabel = "label--info" ; break;
                case "stopped": alabel = "label--dkgray" ; break;
                case "failed":  alabel = "label--danger"; break;
                default:        alabel = "label--default";
            }
            return '<span class="label '+alabel+'">'+text+'</span>'
        } else if(attr == "description"){
            if(text.length==0){ return "-" }
            return text
        }
        return text
    }
}

function fabricSettings(){
    baseModelObject.call(this)
    var self = this
    self.settings = ko.observable("default")
    self.email_address = ko.observable("")
    self.syslog_server = ko.observable("")
    self.syslog_port = ko.observable(514)
    self.notify_move_email = ko.observable(false)
    self.notify_stale_email = ko.observable(false)
    self.notify_offsubnet_email = ko.observable(false)
    self.notify_clear_email = ko.observable(false)
    self.notify_rapid_email = ko.observable(false)
    self.notify_move_syslog = ko.observable(false)
    self.notify_stale_syslog = ko.observable(false)
    self.notify_offsubnet_syslog = ko.observable(false)
    self.notify_clear_syslog = ko.observable(false)
    self.notify_rapid_syslog = ko.observable(false)
    self.auto_clear_stale = ko.observable(false)
    self.auto_clear_offsubnet = ko.observable(false)
    self.anaylze_move = ko.observable(true)
    self.anaylze_offsubnet = ko.observable(true)
    self.anaylze_stale = ko.observable(true)
    self.anaylze_rapid = ko.observable(true)
    self.refresh_rapid = ko.observable(true)
    self.max_per_node_endpoint_events = ko.observable(64)
    self.max_endpoint_events = ko.observable(64)
    self.queue_init_events = ko.observable(true)
    self.queue_init_epm_events = ko.observable(true)
    self.stale_no_local = ko.observable(true)
    self.stale_multiple_local = ko.observable(true)
    self.rapid_threshold = ko.observable(1024)
    self.rapid_holdtime = ko.observable(600)
}

function fabric(fabric_name) {
    baseModelObject.call(this)
    var self = this
    self._subtypes = {"events": fabricEvent}
    self.fabric = ko.observable(fabric_name)
    self.settings = new fabricSettings()
    self.apic_username = ko.observable("")
    self.apic_password = ko.observable("")
    self.apic_hostname = ko.observable("")
    self.apic_cert = ko.observable("")
    self.ssh_username = ko.observable("")
    self.ssh_password = ko.observable("")
    self.events = ko.observableArray([])
    self.event_count = ko.observable(0)
    self.status = ko.observable("")
    self.count_mac = ko.observable(".")
    self.count_ipv4 = ko.observable(".")
    self.count_ipv6 = ko.observable(".")
    self.loading_fabric = ko.observable(false)
    self.loading_settings = ko.observable(false)
    self.loading_status = ko.observable(false)
    self.loading_count_mac = ko.observable(false)
    self.loading_count_ipv4 = ko.observable(false)
    self.loading_count_ipv6 = ko.observable(false)

    self.isLoading = ko.computed(function(){
        return (self.loading_fabric() || self.loading_settings() || self.loading_status() || 
                self.loading_count_mac() || self.loading_count_ipv4() || self.loading_count_ipv6())
    })

    // custom cell formatting per attribute
    self.formatter = function(attr, text){
        if(attr == "status"){
            return '<span class="'+get_status_label(text)+'">'+text+'</span>'
        } else if (attr == "fabric"){
            return '<span class="text-bold">'+text+'</span>'
        }
        return text
    }

    // refresh full state for this fabric (fabric, settings, status, and counts)
    self.refresh = function(success){
        if(success===undefined){ success = function(){}}
        self.loading_fabric(true)
        self.loading_settings(true)
        self.loading_status(true)
        self.loading_count_mac(true)
        self.loading_count_ipv4(true)
        self.loading_count_ipv6(true)
        var base = "/api/uni/fb-"+self.fabric()
        var count_base = "/api/ept/endpoint?count=1&filter=and(eq(\"fabric\",\""+self.fabric()+"\"),neq(\"events.0.status\",\"deleted\"),"
        json_get(base, function(data){
            if(data.objects.length>0){
                self.fromJS(data.objects[0].fabric)
            }
            self.loading_fabric(false)
            if(!self.isLoading()){success()}
        })
        json_get(base+"/settings-default", function(data){
            if(data.objects.length>0){
                self.settings.fromJS(data.objects[0]["ept.settings"])
            }
            self.loading_settings(false)
            if(!self.isLoading()){success()}
        })
        json_get(base+"/status", function(data){
            self.status(data.status)
            self.loading_status(false)
            if(!self.isLoading()){success()}
        })
        json_get(count_base+"eq(\"type\",\"mac\"))", function(data){
            self.count_mac(data.count)
            self.loading_count_mac(false)
            if(!self.isLoading()){success()}
        })
        json_get(count_base+"eq(\"type\",\"ipv4\"))", function(data){
            self.count_ipv4(data.count)
            self.loading_count_ipv4(false)
            if(!self.isLoading()){success()}
        })
        json_get(count_base+"eq(\"type\",\"ipv6\"))", function(data){
            self.count_ipv6(data.count)
            self.loading_count_ipv6(false)
            if(!self.isLoading()){success()}
        })
    }
}

// general event used by eptEndpoint, eptHistory, eptStale, etc...
function generalEvent(){
    baseModelObject.call(this)
    var self = this
    self.ts = ko.observable(0)
    self.status = ko.observable("")
    self.intf_id = ko.observable("")
    self.intf_name = ko.observable("")
    self.pctag = ko.observable(0)
    self.encap = ko.observable("")
    self.rw_mac = ko.observable("")
    self.rw_bd = ko.observable(0)
    self.epg_name = ko.observable("")
    self.vnid_name = ko.observable("")
    self.node = ko.observable(0)
    self.remote = ko.observable(0)
    self.classname = ko.observable("")
    self.flags = ko.observableArray([])
    self.ts_str = ko.computed(function(){
        return timestamp_to_string(self.ts())
    }) 
}

function eptEndpoint(){
    baseModelObject.call(this)
    var self = this
    self._subtypes = {"events": generalEvent, "first_learn":generalEvent }
    self.first_learn = new generalEvent()
    self.fabric = ko.observable("")
    self.vnid = ko.observable(0)
    self.addr = ko.observable("")
    self.type = ko.observable("")
    self.is_stale = ko.observable(false)
    self.is_offsubnet = ko.observable(false)
    self.is_rapid = ko.observable(false)
    self.is_rapid_ts = ko.observable(0)
    self.events = ko.observableArray([])
    self.count = ko.observable(0)

    //set to events.0 or first_learn with preference over events.0
    self.vnid_name = ko.computed(function(){
        var name = ""
        if(self.events().length>0 && self.events()[0].vnid_name().length>0){ 
            name = self.events()[0].vnid_name(); 
        }
        else{ name = self.first_learn.vnid_name() }
        if(name.length>0){ return name }
        return "-"
    })
    self.epg_name = ko.computed(function(){
        var name = ""
        if(self.events().length>0 && self.events()[0].epg_name().length){ 
            name = self.events()[0].epg_name(); 
        }
        else{ name = self.first_learn.epg_name() }
        if(name.length>0){ return name }
        return "-"
    })
    // custom cell formatting per attribute
    self.formatter = function(attr, text){
        if(attr == "type"){
            return '<span class="'+get_endpoint_type_label(text)+'">'+text+'</span>'
        }
        else if(attr == "addr"){
            var url = '#/fb-'+self.fabric()+'/vnid-'+self.vnid()+'/addr-'+self.addr()
            return '<a href="'+url+'">'+text+'</a>'
        }
        return text
    }
}

function moveEvent(){
    baseModelObject.call(this)
    var self = this
    self._subtypes = {"src": generalEvent, "dst":generalEvent }
    self.src = new generalEvent()
    self.dst = new generalEvent()
    self.ts_str = ko.computed(function(){
        return self.dst.ts_str()
    })
}

function eptMove(){
    baseModelObject.call(this)
    var self = this
    self._subtypes = {"events": moveEvent }
    self.fabric = ko.observable("")
    self.vnid = ko.observable(0)
    self.addr = ko.observable("")
    self.type = ko.observable("")
    self.events = ko.observableArray([])
    self.count = ko.observable(0)

    //get ts_str from first event
    self.ts_str = ko.computed(function(){
        if(self.events().length>0){ return self.events()[0].dst.ts_str() }
        return "-"
    })
    // get vnid_name from events.0
    self.vnid_name = ko.computed(function(){
        var name = ""
        if(self.events().length>0 && self.events()[0].dst.vnid_name().length>0){ 
            name = self.events()[0].dst.vnid_name(); 
        }
        if(name.length>0){ return name }
        return "-"
    })
    // custom cell formatting per attribute
    self.formatter = function(attr, text){
        if(attr == "type"){
            return '<span class="'+get_endpoint_type_label(text)+'">'+text+'</span>'
        }
        else if(attr == "addr"){
            var url = '#/fb-'+self.fabric()+'/vnid-'+self.vnid()+'/addr-'+self.addr()
            return '<a href="'+url+'">'+text+'</a>'
        }
        return text
    }
}

function eptOffsubnet(){
    baseModelObject.call(this)
    var self = this
    self._subtypes = {"events": generalEvent }
    self.fabric = ko.observable("")
    self.vnid = ko.observable(0)
    self.addr = ko.observable("")
    self.type = ko.observable("")
    self.node = ko.observable(0)
    self.events = ko.observableArray([])
    self.count = ko.observable(0)

    //get ts_str from first event
    self.ts_str = ko.computed(function(){
        if(self.events().length>0){ return self.events()[0].ts_str() }
        return "-"
    })

    // get vnid_name from events.0
    self.vnid_name = ko.computed(function(){
        var name = ""
        if(self.events().length>0 && self.events()[0].vnid_name().length>0){ 
            name = self.events()[0].vnid_name(); 
        }
        if(name.length>0){ return name }
        return "-"
    })
    // custom cell formatting per attribute
    self.formatter = function(attr, text){
        if(attr == "type"){
            return '<span class="'+get_endpoint_type_label(text)+'">'+text+'</span>'
        }
        else if(attr == "addr"){
            var url = '#/fb-'+self.fabric()+'/vnid-'+self.vnid()+'/addr-'+self.addr()
            return '<a href="'+url+'">'+text+'</a>'
        }
        return text
    }
}

function eptStale(){
    baseModelObject.call(this)
    var self = this
    self._subtypes = {"events": generalEvent }
    self.fabric = ko.observable("")
    self.vnid = ko.observable(0)
    self.addr = ko.observable("")
    self.type = ko.observable("")
    self.node = ko.observable(0)
    self.events = ko.observableArray([])
    self.count = ko.observable(0)

    //get ts_str from first event
    self.ts_str = ko.computed(function(){
        if(self.events().length>0){ return self.events()[0].ts_str() }
        return "-"
    })

    // get vnid_name from events.0
    self.vnid_name = ko.computed(function(){
        var name = ""
        if(self.events().length>0 && self.events()[0].vnid_name().length>0){ 
            name = self.events()[0].vnid_name(); 
        }
        if(name.length>0){ return name }
        return "-"
    })
    // custom cell formatting per attribute
    self.formatter = function(attr, text){
        if(attr == "type"){
            return '<span class="'+get_endpoint_type_label(text)+'">'+text+'</span>'
        }
        else if(attr == "addr"){
            var url = '#/fb-'+self.fabric()+'/vnid-'+self.vnid()+'/addr-'+self.addr()
            return '<a href="'+url+'">'+text+'</a>'
        }
        return text
    }
}

function eptHistory(){
    baseModelObject.call(this)
    var self = this
    self._subtypes = {"events": generalEvent }
    self.fabric = ko.observable("")
    self.vnid = ko.observable(0)
    self.addr = ko.observable("")
    self.type = ko.observable("")
    self.node = ko.observable(0)
    self.is_stale = ko.observable(false)
    self.is_offsubnet = ko.observable(false)
    self.events = ko.observableArray([])
    self.count = ko.observable(0)

    //get ts_str from first event
    self.ts_str = ko.computed(function(){
        if(self.events().length>0){ return self.events()[0].ts_str() }
        return "-"
    })
    self.status_str = ko.computed(function(){
        if(self.events().length>0){ return self.events()[0].status() }
        return "-"
    })

    // get vnid_name from events.0
    self.vnid_name = ko.computed(function(){
        var name = ""
        if(self.events().length>0 && self.events()[0].vnid_name().length>0){ 
            name = self.events()[0].vnid_name(); 
        }
        if(name.length>0){ return name }
        return "-"
    })
    // custom cell formatting per attribute
    self.formatter = function(attr, text){
        if(attr == "type"){
            return '<span class="'+get_endpoint_type_label(text)+'">'+text+'</span>'
        }
        else if(attr == "addr"){
            var url = '#/fb-'+self.fabric()+'/vnid-'+self.vnid()+'/addr-'+self.addr()
            return '<a href="'+url+'">'+text+'</a>'
        }
        else if(attr == "status_str"){
            return '<span class="'+get_status_label(text)+'">'+text+'</span>'
        }
        return text
    }
}

// general event used by eptRapid
function rapidEvent(){
    baseModelObject.call(this)
    var self = this
    self.ts = ko.observable(0)
    self.ts_str = ko.computed(function(){
        return timestamp_to_string(self.ts())
    }) 
    self.rate = ko.observable(0)    
    // endpoint count when rapid was triggered
    self.count = ko.observable(0)   
}

function eptRapid(){
    baseModelObject.call(this)
    var self = this
    self._subtypes = {"events": rapidEvent }
    self.fabric = ko.observable("")
    self.vnid = ko.observable(0)
    self.addr = ko.observable("")
    self.type = ko.observable("")
    self.events = ko.observableArray([])
    self.count = ko.observable(0)

    //get ts_str from first event
    self.ts_str = ko.computed(function(){
        if(self.events().length>0){ return self.events()[0].ts_str() }
        return "-"
    })

    // get vnid_name from events.0
    self.vnid_name = ko.computed(function(){
        var name = ""
        if(self.events().length>0 && self.events()[0].vnid_name().length>0){ 
            name = self.events()[0].vnid_name(); 
        }
        if(name.length>0){ return name }
        return "-"
    })
    // custom cell formatting per attribute
    self.formatter = function(attr, text){
        if(attr == "type"){
            return '<span class="'+get_endpoint_type_label(text)+'">'+text+'</span>'
        }
        else if(attr == "addr"){
            var url = '#/fb-'+self.fabric()+'/vnid-'+self.vnid()+'/addr-'+self.addr()
            return '<a href="'+url+'">'+text+'</a>'
        }
        return text
    }
}

// general event used by eptEndpoint, eptHistory, eptStale, etc...
function remediateEvent(){
    baseModelObject.call(this)
    var self = this
    self.ts = ko.observable(0)
    self.ts_str = ko.computed(function(){
        return timestamp_to_string(self.ts())
    }) 
    self.action = ko.observable("")
    self.reason = ko.observable("")
}

function eptRemediate(){
    baseModelObject.call(this)
    var self = this
    self._subtypes = {"events": remediateEvent }
    self.fabric = ko.observable("")
    self.vnid = ko.observable(0)
    self.addr = ko.observable("")
    self.type = ko.observable("")
    self.node = ko.observable(0)
    self.events = ko.observableArray([])
    self.count = ko.observable(0)

    //get ts_str from first event
    self.ts_str = ko.computed(function(){
        if(self.events().length>0){ return self.events()[0].ts_str() }
        return "-"
    })

    // get action/reason from events.0
    self.action = ko.computed(function(){
        if(self.events().length>0 && self.events()[0].action().length>0){ 
                return self.events()[0].action()
        }
        return "-"
    })
    // get action/reason from events.0
    self.reason = ko.computed(function(){
        if(self.events().length>0 && self.events()[0].reason().length>0){ 
                return self.events()[0].reason()
        }
        return "-"
    })

    // custom cell formatting per attribute
    self.formatter = function(attr, text){
        if(attr == "type"){
            return '<span class="'+get_endpoint_type_label(text)+'">'+text+'</span>'
        }
        else if(attr == "addr"){
            var url = '#/fb-'+self.fabric()+'/vnid-'+self.vnid()+'/addr-'+self.addr()
            return '<a href="'+url+'">'+text+'</a>'
        }
        return text
    }
}


