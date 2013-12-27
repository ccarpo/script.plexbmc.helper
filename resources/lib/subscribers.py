import re
import threading
import xbmcgui
from xml.dom.minidom import parseString
from functions import *
from settings import settings
from httppersist import requests

class SubscriptionManager:
    def __init__(self):
        self.subscribers = {}
        self.info = {}
        self.lastkey = ""
        self.volume = 0
        self.guid = ""
        self.server = ""
        self.protocol = "http"
        self.port = ""
        
    def getVolume(self):
        self.volume = getVolume()

    def msg(self, players):
        msg = getXMLHeader()
        msg += '<MediaContainer commandID="INSERTCOMMANDID"'
        if players:
            self.getVolume()
            maintype = plex_audio()
            for p in players.values():
                if p.get('type') == xbmc_video():
                    maintype = plex_video()
                elif p.get('type') == xbmc_photo():
                    maintype = plex_photo()
            self.mainlocation = "fullScreen" + maintype[0:1].upper() + maintype[1:].lower()
        else:
            self.mainlocation = "navigation"
        msg += ' location="%s">' % self.mainlocation
       
        msg += self.getTimelineXML(getAudioPlayerId(players), plex_audio())
        msg += self.getTimelineXML(getPhotoPlayerId(players), plex_photo())
        msg += self.getTimelineXML(getVideoPlayerId(players), plex_video())
        msg += "\r\n</MediaContainer>"
        return msg
        
    def getTimelineXML(self, playerid, ptype):
        if playerid > 0:
            info = self.getPlayerProperties(playerid)
            state = info['state']
            time = info['time']
        else:
            state = "stopped"
            time = 0
        ret = "\r\n"+'<Timeline location="%s" state="%s" time="%s" type="%s"' % (self.mainlocation, state, time, ptype)
        if playerid > 0:
            WINDOW = xbmcgui.Window(10000)
            pbmc_server = str(WINDOW.getProperty('plexbmc.nowplaying.server'))
            keyid = str(WINDOW.getProperty('plexbmc.nowplaying.id'))
            if keyid:
                self.lastkey = "/library/metadata/%s"%keyid
                if pbmc_server:
                    (self.server, self.port) = pbmc_server.split(':')
            serv = getServerByHost(self.server)
            ret += ' duration="%s"' % info['duration']
            ret += ' seekRange="0-%s"' % info['duration']
            ret += ' controllable="%s"' % self.controllable()
            ret += ' machineIdentifier="%s"' % serv.get('uuid', "")
            ret += ' protocol="%s"' % serv.get('protocol', "http")
            ret += ' address="%s"' % serv.get('server', self.server)
            ret += ' port="%s"' % serv.get('port', self.port)
            ret += ' guid="%s"' % info['guid']
            ret += ' containerKey="%s"' % (self.lastkey or "/library/metadata/900000")
            ret += ' key="%s"' % (self.lastkey or "/library/metadata/900000")
            m = re.search(r'(\d+)$', self.lastkey)
            if m:
                ret += ' ratingKey="%s"' % m.group()
            ret += ' volume="%s"' % info['volume']
            ret += ' shuffle="%s"' % info['shuffle']
        
        ret += '/>'
        return ret
     
    def updateCommandID(self, uuid, commandID):
        if commandID and self.subscribers.get(uuid, False):
            self.subscribers[uuid].commandID = int(commandID)            
        
    def notify(self, event = False):
        self.cleanup()
        if not self.subscribers:
            return True
        players = getPlayers()
        msg = self.msg(players)
        with threading.RLock():
            for sub in self.subscribers.values():
                sub.send_update(msg, len(players)==0)
        return True
        
    def controllable(self):
        return "playPause,play,stop,skipPrevious,skipNext,volume,stepBack,stepForward,seekTo"
        
    def addSubscriber(self, protocol, host, port, uuid, commandID, poller=False):
        sub = Subscriber(protocol, host, port, uuid, commandID, poller)
        with threading.RLock():
            self.subscribers[sub.uuid] = sub
        return sub
                
    def removeSubscriber(self, uuid):
        with threading.RLock():
            for sub in self.subscribers.values():
                if sub.uuid == uuid or sub.host == uuid:
                    sub.cleanup()
                    del self.subscribers[sub.uuid]
                    
    def cleanup(self):
        with threading.RLock():
            for sub in self.subscribers.values():
                if sub.age > 30:
                    sub.cleanup()
                    del self.subscribers[sub.uuid]
            
    def getPlayerProperties(self, playerid):
        info = {}
        try:
            # get info from the player
            props = jsonrpc("Player.GetProperties", {"playerid": playerid, "properties": ["time", "totaltime", "speed", "shuffled"]})
            printDebug(jsonrpc("Player.GetItem", {"playerid": playerid, "properties": ["file", "showlink", "episode", "season"]}))
            info['time'] = timeToMillis(props['time'])
            info['duration'] = timeToMillis(props['totaltime'])
            info['state'] = ("paused", "playing")[int(props['speed'])]
            info['shuffle'] = ("0","1")[props.get('shuffled', False)]            
        except:
            info['time'] = 0
            info['duration'] = 0
            info['state'] = "stopped"
            info['shuffle'] = False
        # get the volume from the application
        info['volume'] = self.volume
        info['guid'] = self.guid

        return info

class Subscriber:
    def __init__(self, protocol, host, port, uuid, commandID, poller=False):
        self.protocol = protocol or "http"
        self.host = host
        self.port = port or 32400
        self.uuid = uuid or host
        self.commandID = int(commandID) or 0
        self.navlocationsent = False
        self.age = 0
    def __eq__(self, other):
        return self.uuid == other.uuid
    def tostr(self):
        return "uuid=%s,commandID=%i" % (self.uuid, self.commandID)
    def cleanup(self):
        requests.closeConnection(self.protocol, self.host, self.port)
    def send_update(self, msg, is_nav):
        self.age += 1
        if not is_nav:
            self.navlocationsent = False
        elif self.navlocationsent:
            return True
        else:
            self.navlocationsent = True
        msg = re.sub(r"INSERTCOMMANDID", str(self.commandID), msg)
        printDebug("sending xml to subscriber %s: %s" % (self.tostr(), msg))
        if not requests.post(self.host, self.port, "/:/timeline", msg, getPlexHeaders(), self.protocol):
            subMgr.removeSubscriber(self.uuid)

subMgr = SubscriptionManager()    