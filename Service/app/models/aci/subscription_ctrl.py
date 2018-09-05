"""
    ACI App subscription_ctrl
    @author agossett@cisco.com
"""

import logging, threading, time, traceback
from .utils import (get_dn, get_apic_session)

# module level logging
logger = logging.getLogger(__name__)

class SubscriptionCtrl(object):
    """ subscription controller """

    CTRL_QUIT    = 1
    CTRL_CONTINUE= 2

    def __init__(self, fabric, interests, **kwargs):
        """
            fabric (str or instance of Fabric object)

            {
                "classname": {          # classname in which to subscribe
                    "handler": <func>   # callback function for object event
                                        # must accept single event argument
                },
            }  
            each event is dict with following attributes:
                "_ts": float timestamp event was received on server
                "imdata": list of objects within the event

            additional kwargs:
            only_new (bool)     do not return existing objects, only new 
                                events recevied on the subscription    
            heartbeat (int)     dead interval to check health of session
            inactive_interval(float) interval in seconds to sleep between loop
                                when no events have been detected and no 
                                callbacks are ready
            subscribe_timeout(int) maximum amount of time to wait for 
                                non-blocking subscription to start. If exceeded
                                the subscription is aborted
        """

        self.fabric = fabric
        self.interests = interests
        self.only_new  = kwargs.get("only_new", True)
        self.heartbeat = kwargs.get("heartbeat", 60.0)
        self.inactive_interval = kwargs.get("inactive_interval", 0.5)
        self.subscribe_timeout = kwargs.get("subscribe_timeout", 10.0)

        # state of the session
        self.worker_thread = None
        self.last_heartbeat = 0
        self.session = None
        self.alive = False
        self.lock = threading.Lock()
        self.ctrl = SubscriptionCtrl.CTRL_CONTINUE

    def is_alive(self):
        """ determine if subscription is still alive """
        return self.alive

    def restart(self, blocking=True):
        """ restart subscription
       
            blocking (bool)     by default subscriptions block while the 
                                subscription is active. If blocking is set to
                                false then subscription is handled in background     
        """
        # if subscription is already active, wait for it close
        self.unsubscribe()
        self.subscribe(blocking=blocking)
  
    def unsubscribe(self):
        """ unsubscribe and close connections """
        logger.debug("unsubscribe: (alive: %r, threaded: %r)", self.alive,
            (self.worker_thread is not None))
        if not self.alive: return

        # should never call unsubscribe without worker (subscribe called with
        # block=True), however as sanity check let's put it in there...
        if self.worker_thread is None:
            self._close_subscription()
            return

        # get lock to set ctrl
        logger.debug("setting ctrl to close")
        with self.lock:
            self.ctrl = SubscriptionCtrl.CTRL_QUIT
           
        # wait for child thread to die
        logger.debug("waiting for worker thread to exit")
        self.worker_thread.join() 
        self.worker_thread = None
        logger.debug("worker thread closed")
 
    def subscribe(self, blocking=True):
        """ start subscription and handle appropriate callbacks 

            blocking (bool)     by default subscriptions block while the 
                                subscription is active. If blocking is set to
                                false then subscription is handled in background

            Note, when blocking=False, the main thread will still wait until
            subscription has successfully started (or failed) before returning
        """
        logger.debug("start subscribe (blocking:%r)", blocking)

        # get lock to set ctrl
        logger.debug("setting ctrl to close")
        with self.lock:
            self.ctrl = SubscriptionCtrl.CTRL_CONTINUE

        # never try to subscribe without first killing previous sessions
        self.unsubscribe()
        if blocking: 
            self._subscribe()
        else:
            self.worker_thread = threading.Thread(target=self._subscribe)
            self.worker_thread.daemon = True
            self.worker_thread.start()
            
            # wait until subscription is alive or exceeds timeout
            ts = time.time()
            while not self.alive:
                if time.time() - ts  > self.subscribe_timeout:
                    logger.debug("failed to start subscription")
                    self.unsubscribe()
                    return
                logger.debug("waiting for subscription to start")
                time.sleep(1) 
        logger.debug("subscription successfully started")

    def _subscribe(self):
        """ handle subscription within thread """
        logger.debug("subscription thread starting")

        # initialize subscription is not alive
        self.alive = False

        # dummy function that does nothing
        def noop(*args,**kwargs): pass

        # verify caller arguments
        if type(self.interests) is not dict or len(self.interests)==0:
            logger.error("invalid interests for subscription: %s", interest)
            return

        for cname in self.interests:
            if type(self.interests[cname]) is not dict or \
                "handler" not in self.interests[cname]:
                logger.error("invalid interest %s: %s", cname, 
                    self.interest[cname])
                return
            if not callable(self.interests[cname]["handler"]):
                logger.error("handler '%s' for %s is not callable", 
                    self.interests[cname]["handler"], cname)
                return
    
        try: self.heartbeat = float(self.heartbeat)
        except ValueError as e:
            logger.warn("invalid heartbeat '%s' setting to 60.0",self.heartbeat)
            heartbeat = 60.0

        # create session to fabric
        self.session = get_apic_session(self.fabric, subscription_enabled=True)
        if self.session is None:
            logger.error("subscription failed to connect to fabric %s",
                self.fabric)
            return

        for cname in self.interests:
            # assume user knows what they are doing here - if only_new is True then return set is
            # limited to first 10.  Else, page-size is set to maximum
            if self.only_new:
                url = "/api/class/%s.json?subscription=yes&page-size=10" % cname
            else:
                url = "/api/class/%s.json?subscription=yes&page-size=75000" % cname
            self.interests[cname]["url"] = url
            resp = self.session.subscribe(url, only_new=self.only_new)
            if resp is None or not resp.ok:
                logger.warn("failed to subscribe to %s",  cname)
                return
            logger.debug("successfully subscribed to %s", cname)

        # successfully subscribed to all objects
        self.alive = True
    
        # listen for events and send to handler
        self.last_heartbeat = time.time()
        while True:
            # check ctrl flags and exit if set to quit
            if self.ctrl != SubscriptionCtrl.CTRL_CONTINUE:
                logger.debug("exiting subscription due to ctrl: %s",self.ctrl)
                self._close_subscription()
                return

            interest_found = False
            ts = time.time()
            for cname in self.interests:
                url = self.interests[cname]["url"]
                count = self.session.get_event_count(url)
                if count > 0:
                    logger.debug("1/%s events found for %s", count, cname)
                    self.interests[cname]["handler"](self.session.get_event(url))
                    interest_found = True

            # update last_heartbeat or if exceed heartbeat, check session health
            if interest_found: 
                self.last_heartbeat = ts
            elif (ts-self.last_heartbeat) > self.heartbeat:
                logger.debug("checking session status, last_heartbeat: %s",
                    self.last_heartbeat)
                if not self.check_session_subscription_health():
                    logger.warn("session no longer alive")
                    self._close_subscription()
                    return
                self.last_heartbeat = ts
            else: time.sleep(self.inactive_interval)

    def _close_subscription(self):
        """ try to close any open subscriptions """
        logger.debug("close all subscriptions")
        self.alive = False
        if self.session is not None:
            try:
                urls = self.session.subscription_thread._subscriptions.keys()
                for url in urls:
                    if "?" in url: url = "%s&page-size=1" % url
                    else: url = "%s?page-size=1" % url
                    logger.debug("close subscription url: %s", url)
                    self.session.unsubscribe(url)
                self.session.close()
            except Exception as e:
                logger.warn("failed to close subscriptions: %s", e)
                logger.debug(traceback.format_exc())

    def check_session_subscription_health(self):
        """ check health of session subscription thread and that corresponding
            websocket is still connected.  Additionally, perform query on uni to 
            ensure connectivity to apic is still present
            return True if all checks pass else return False
        """
        alive = False
        try:
            alive = (
                hasattr(self.session.subscription_thread, "is_alive") and \
                self.session.subscription_thread.is_alive() and \
                hasattr(self.session.subscription_thread, "_ws") and \
                self.session.subscription_thread._ws.connected and \
                get_dn(self.session, "uni", timeout=3) is not None
            )
        except Exception as e: pass
        logger.debug("manual check to ensure session is still alive: %r",alive)
        return alive

if __name__ == "__main__":
    
    from ..utils import (pretty_print, setup_logger)
    def handle(event): 
        logger.debug("event: %s", pretty_print(event))

    setup_logger(logger, stdout=True, quiet=True, thread=True)
    logger.debug("let's start this...")

    fabric = "fab3"
    interests = {
        "fvTenant": {"handler": handle},
        "fvBD": {"handler": handle},
        "eqptLC": {"handler": handle},
    }
    sub = SubscriptionCtrl(fabric, interests)
    sub.heartbeat = 10
    try:
        sub.subscribe(blocking=True)
    except KeyboardInterrupt as e:
        logger.debug("interrupting main thread!")
    finally:
        sub.unsubscribe()
