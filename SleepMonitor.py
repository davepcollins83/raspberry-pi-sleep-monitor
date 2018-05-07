#!/usr/bin/env python

from twisted.internet import reactor, protocol, defer, interfaces, ssl
import twisted.internet.error
from twisted.web import server, resource
from twisted.web.static import File
from zope.interface import implementer
from threading import Timer

import re
from datetime import datetime, timedelta
import os
import json
import subprocess
import io

# added for temp sensor:
import glob
import time

from neopixel import *

# LED strip configuration:
LED_COUNT      = 7      # Number of LED pixels.
LED_PIN        = 10      # GPIO pin connected to the pixels (must support PWM!).
LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
LED_DMA        = 10      # DMA channel to use for generating signal (try 10)
LED_BRIGHTNESS = 200     # Set to 0 for darkest and 255 for brightest
LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)
LED_CHANNEL    = 0
LED_STRIP      = ws.SK6812_STRIP_GRBW

# added for i2c
import smbus
bus = smbus.SMBus(1)

# This is the address we setup in the Arduino Program
address = 0x04

from ProcessProtocolUtils import spawnNonDaemonProcess, \
        TerminalEchoProcessProtocol
from OximeterReader import OximeterReader
from ZeroConfUtils import startZeroConfServer

from LoggingUtils import log, setupLogging, LoggingProtocol

from Config import Config
from Constants import MotionReason

# for Jinja2 templates

template_dir = '{}/web/'.format(os.path.dirname(os.path.realpath(__file__)))

# for temp reading

os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')

base_dir = '/sys/bus/w1/devices/'
device_folder = glob.glob(base_dir + '28*')[0]
device_file = device_folder + '/w1_slave'

def ClearSheep(app):
    app.sheepPlaying = 0
    app.t.cancel()
    log('Clear')

class RepeatingTimer(object):

    def __init__(self, interval, f, *args, **kwargs):
        self.interval = interval
        self.f = f
        self.args = args
        self.kwargs = kwargs

        #self.timer = None
        self.timer = Timer(self.interval, self.callback)

    def callback(self):
        self.f(*self.args, **self.kwargs)
        #self.start()

    def cancel(self):
        self.timer.cancel()

    def start(self):
        #self.timer = Timer(self.interval, self.callback)
        self.timer.start()

#t = RepeatingTimer(10, ClearSheep)

def read_temp_raw():
    f = open(device_file, 'r')
    lines = f.readlines()
    f.close()
    return lines

def read_temp():
    lines = read_temp_raw()
    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw()
    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        temp_string = lines[1][equals_pos+2:]
        temp_c = float(temp_string) / 1000.0
        # temp_f = temp_c * 9.0 / 5.0 + 32.0
        return temp_c

# for i2c

def writeDigispark(device, i2cData):
	bus.write_i2c_block_data(address, device, i2cData)
	return -1


def async_sleep(seconds):
    d = defer.Deferred()
    reactor.callLater(seconds, d.callback, seconds)
    return d

class MJpegResource(resource.Resource):
    def __init__(self, queues):
        self.queues = queues

    def setupProducer(self, request):
        producer = JpegProducer(request)
        request.notifyFinish().addErrback(self._responseFailed, producer)
        request.registerProducer(producer, True)

        self.queues.append(producer)

    def _responseFailed(self, err, producer):
        log('connection to client lost')
        producer.stopProducing()

    def render_GET(self, request):
        log('getting new client of image stream')
        request.setHeader("content-type", 'multipart/x-mixed-replace; boundary=--spionisto')

        self.setupProducer(request)
        return server.NOT_DONE_YET

class LatestImageResource(resource.Resource):
    def __init__(self, factory):
        self.factory = factory

    def render_GET(self, request):
        request.setHeader("content-type", 'image/jpeg')
        return self.factory.latestImage

@implementer(interfaces.IPushProducer)
class JpegProducer(object):
    def __init__(self, request):
        self.request = request
        self.isPaused = False
        self.isStopped = False
        self.delayedCall = None

    def cancelCall(self):
        if self.delayedCall:
            self.delayedCall.cancel()
            self.delayedCall = None

    def pauseProducing(self):
        self.isPaused = True
        self.cancelCall()
        # log('producer is requesting to be paused')

    def resetPausedFlag(self):
        self.isPaused = False
        self.delayedCall = None

    def resumeProducing(self):
        # calling self.cancelCall is defensive. We should not really get
        # called with multiple resumeProducing calls without any
        # pauseProducing in the middle.
        self.cancelCall()
        self.delayedCall = reactor.callLater(1, self.resetPausedFlag)
        # log('producer is requesting to be resumed')

    def stopProducing(self):
        self.isPaused = True
        self.isStopped = True
        log('producer is requesting to be stopped')

MJPEG_SEP = '--spionisto\r\n'

class JpegStreamReader(protocol.Protocol):
    def __init__(self):
        self.tnow = None

    def connectionMade(self):
        log('MJPEG Image stream received')
        self.data = ''
        self.tnow = datetime.now()
        self.cumDataLen = 0
        self.cumCalls = 0

    def dataReceived(self, data):
        self.data += data

        chunks = self.data.rsplit(MJPEG_SEP, 1)

        dataToSend = ''
        if len(chunks) == 2:
            subchunks = chunks[0].rsplit(MJPEG_SEP, 1)

            lastchunk = subchunks[-1]
            idx = lastchunk.find(b'\xff\xd8\xff')
            self.factory.latestImage = lastchunk[idx:]

            dataToSend = chunks[0] + MJPEG_SEP

        self.data = chunks[-1]

        self.cumDataLen += len(dataToSend)
        self.cumCalls += 1

        for producer in self.factory.queues:
            if (not producer.isPaused):
                producer.request.write(dataToSend)

        if datetime.now() - self.tnow > timedelta(seconds=1):
            # log('Wrote %d bytes in the last second (%d cals)' % (self.cumDataLen, self.cumCalls))
            self.tnow = datetime.now()
            self.cumDataLen = 0
            self.cumCalls = 0

class MotionDetectionStatusReaderProtocol(TerminalEchoProcessProtocol):
    PAT_STATUS = re.compile(r'(\d) (\d)')

    def __init__(self, app):
        TerminalEchoProcessProtocol.__init__(self)
        self.motionDetected = False
        self.motionSustained = False
        self.app = app

    def outLineReceived(self, line):
        if line.startswith('MOTION_DETECTOR_READY'):
            self.app.startGstreamerVideo()

        if self.PAT_STATUS.match(line):
            (self.motionDetected, self.motionSustained) = [int(word) for word in line.split()]
        else:
            log('MotionDetector: %s' % line)

    def errLineReceived(self, line):
        log('MotionDetector: error: %s' % line)

    def reset(self):
        self.transport.write('reset\n')

class StatusResource(resource.Resource):
    def __init__(self, app):
        self.app = app
        self.motionDetectorStatusReader = self.app.motionDetectorStatusReader
        self.oximeterReader = self.app.oximeterReader

    def render_GET(self, request):
        request.setHeader("content-type", 'application/json')

        motion = 0
        motionReason = MotionReason.NONE
        if self.motionDetectorStatusReader.motionSustained:
            motion = 1
            motionReason = MotionReason.CAMERA
        elif self.oximeterReader.motionSustained:
            motion = 1
            motionReason = MotionReason.BPM
        # Add line in here to detect motion based on sound

        status = {
            'SPO2': self.oximeterReader.SPO2,
            'BPM': self.oximeterReader.BPM,
            'alarm': bool(self.oximeterReader.alarm),
            'motion': motion,
            'motionReason': motionReason,
            'readTime': self.oximeterReader.readTime.isoformat(),
            'oximeterStatus': self.oximeterReader.status,
            'sheepWatching' : self.app.sheepWatching,
            'sheepPlaying' : self.app.sheepPlaying,
            'lamp' : self.app.lamp,
            'temp' : self.app.temp
        }
        return json.dumps(status)

class PingResource(resource.Resource):
    def render_GET(self, request):
        request.setHeader("content-type", 'application/json')
        request.setHeader("Access-Control-Allow-Origin", '*')

        status = {'status': 'ready'}
        return json.dumps(status)

class GetConfigResource(resource.Resource):
    def __init__(self, app):
        self.app = app

    def render_GET(self, request):
        request.setHeader("content-type", 'application/json')

        status = {}
        for paramName in self.app.config.paramNames:
            status[paramName] = getattr(self.app.config, paramName)

        return json.dumps(status)

class UpdateConfigResource(resource.Resource):
    def __init__(self, app):
        self.app = app

    def render_GET(self, request):
        log('Got request to change parameters to %s' % request.args)

        for paramName in self.app.config.paramNames:
            # a bit of defensive coding. We really should not be getting
            # some random data here.
            if paramName in request.args:
                paramVal = int(request.args[paramName][0])
                log('setting %s to %d' % (paramName, paramVal))
                setattr(self.app.config, paramName, paramVal)

        self.app.resetAfterConfigUpdate()

        request.setHeader("content-type", 'application/json')
        status = {'status': 'done'}
        return json.dumps(status)

class InfluxLoggerClient(LoggingProtocol):
    def __init__(self):
        LoggingProtocol.__init__(self, 'InfluxLogger')

    def log(self, spo2, bpm, motion, alarm, temp):
        self.transport.write('%d %d %d %d %d\n' % (spo2, bpm, motion, alarm, temp))

class Logger:
    def __init__(self, app):
        self.oximeterReader = app.oximeterReader
        self.influxLogger = app.influxLogger
        self.motionDetectorStatusReader = app.motionDetectorStatusReader
        self.temp = app.temp

        self.lastLogTime = datetime.min
        self.logFile = None

        reactor.addSystemEventTrigger('before', 'shutdown', self.closeLastLogFile)

    @defer.inlineCallbacks
    def run(self):
        while True:
            yield async_sleep(2)

            spo2 = self.oximeterReader.SPO2
            bpm = self.oximeterReader.BPM
            alarm = self.oximeterReader.alarm
            motionDetected = self.motionDetectorStatusReader.motionDetected
            temp = self.temp

            self.influxLogger.log(spo2, bpm, motionDetected, alarm, temp)

            tnow = datetime.now()
            if self.oximeterReader.SPO2 != -1:
                tstr = tnow.strftime('%Y-%m-%d-%H-%M-%S')
                motionSustained = self.motionDetectorStatusReader.motionSustained

                logStr = '%(spo2)d %(bpm)d %(alarm)d %(motionDetected)d %(motionSustained)d' % locals()

                # Do not use log here to avoid overloading the log file
                # with stats.
                print('STATUS: %s' % logStr)

                if self.logFile is None:
                    self.createNewLogFile(tstr)

                self.printToFile('%(tstr)s %(logStr)s' % locals())
                self.lastLogTime = tnow
            else:
                if tnow - self.lastLogTime > timedelta(hours=2):
                    self.closeLastLogFile()

    def closeLastLogFile(self):
        if self.logFile is not None:
            self.logFile.close()
            newname = self.logFile.name.replace('.inprogress', '')
            os.rename(self.logFile.name, newname)
            self.logFile = None

    def createNewLogFile(self, tstr):
        bufsize = 1  # line buffering

        if not os.path.isdir('../sleep_logs'):
            os.mkdir('../sleep_logs')

        self.logFile = open('../sleep_logs/%s.log.inprogress' % tstr, 'w', bufsize)

    def printToFile(self, logStr):
        self.logFile.write(logStr + '\n')

def startAudio():
    spawnNonDaemonProcess(reactor, LoggingProtocol('janus'), '/opt/janus/bin/janus',
                          ['janus', '-F', '/opt/janus/etc/janus/'])
    log('Started Janus')

    def startGstreamerAudio():
        #spawnNonDaemonProcess(reactor, LoggingProtocol('gstream-audio'), '/bin/sh',
        #                      ['sh', 'gstream_audio.sh'])
    	spawnNonDaemonProcess(reactor, LoggingProtocol('gstream-audio'), '/usr/bin/python',
                              ['python', 'gstream_audio.py'])
        log('Started gstreamer audio')

    reactor.callLater(2, startGstreamerAudio)

def audioAvailable():
    out = subprocess.check_output(['arecord', '-l'])
    return ('USB Audio' in out)

def startAudioIfAvailable():
    if audioAvailable():
        startAudio()
    else:
        log('Audio not detected. Starting in silent mode')


class GetTemp(resource.Resource):
	def __init__(self, app):
		self.app = app

	def render_GET(self, request):
		request.setHeader("content-type", "text/html")
		temp = read_temp()
		self.app.temp = temp

		return bytes(temp)

class PlayMusic(resource.Resource):
	def __init__(self, app):
		self.app = app

	def render_GET(self, request):

		spawnNonDaemonProcess(reactor, LoggingProtocol('music-player'), '/bin/sh',
                              ['sh', 'play_sound.sh'])
		return

class StopMusic(resource.Resource):
	def __init__(self, app):
		self.app = app

	def render_GET(self, request):

		spawnNonDaemonProcess(reactor, LoggingProtocol('music-player'), '/bin/sh',
                              ['sh', 'stop_sound.sh'])
		return

class ForceMusic(resource.Resource):
	def __init__(self, app):
		self.app = app

	def render_GET(self, request):

		spawnNonDaemonProcess(reactor, LoggingProtocol('music-player'), '/bin/sh',
                              ['sh', 'force_sound.sh'])
		return

def StartSheep(app):
    log('Start Sheep')
    #writeDigispark(1, [1])
    app.t = RepeatingTimer(900, ClearSheep, app)
    app.t.start()

def StopSheep(app):
    log('Stop Sheep')
    #writeDigispark(1, [2])
    app.t.cancel()
    app.t = 0

class ToggleSheep(resource.Resource):
    def __init__(self, app):
        self.app = app

    def render_GET(self, request):
        if self.app.sheepPlaying == 1:
            self.app.sheepPlaying = 0
            StopSheep(self.app)
            spawnNonDaemonProcess(reactor, LoggingProtocol('sheep'), '/bin/sh',
                                  ['sh', 'sheep_off.sh'])
            return

        else:
            self.app.sheepPlaying = 1
            StartSheep(self.app)
            spawnNonDaemonProcess(reactor, LoggingProtocol('sheep'), '/bin/sh',
                                  ['sh', 'sheep_on.sh'])
            return


class SetSheep(resource.Resource):
    def __init__(self, app):
        self.app = app

    def render_GET(self, request):
        if self.app.sheepWatching == 0:
            self.app.sheepWatching = 1
        else:
            self.app.sheepWatching = 0

        return

class ToggleLamp(resource.Resource):
	def __init__(self, app):
		self.app = app

	def render_GET(self, request):

		self.lamp = self.app.lamp
		red = getattr(self.app.config, 'red')
		green = getattr(self.app.config, 'green')
		blue = getattr(self.app.config, 'blue')
		white = getattr(self.app.config, 'white')

		if self.lamp == 0:
			#writeDigispark(2, [1, red, green, blue, white])
			for i in range (0, 6):
				self.app.strip.setPixelColor(i, Color(red, green, blue, white))
				self.app.strip.show()
			self.app.lamp = 1;
			log(self.app.lamp)
			onStr = 'on'
			return onStr
		else:
			#writeDigispark(2, [1, 0, 0, 0, 0])
			for i in range (0, 6):
				self.app.strip.setPixelColor(i, Color(0, 0, 0, 0))
				self.app.strip.show()
			self.app.lamp = 0;
			log(self.app.lamp)
			return 'off'

class ForceLampOn(resource.Resource):
	def __init__(self, app):
		self.app = app

	def render_GET(self, request):

		self.lamp = self.app.lamp
		red = getattr(self.app.config, 'red')
		green = getattr(self.app.config, 'green')
		blue = getattr(self.app.config, 'blue')
		white = getattr(self.app.config, 'white')

		writeDigispark(2, [1, red, green, blue, white])
		self.app.lamp = 1;
		log(self.app.lamp)
		onStr = 'on'
		return onStr

class ForceLampOff(resource.Resource):
	def __init__(self, app):
		self.app = app

	def render_GET(self, request):

		writeDigispark(2, [1, 0, 0, 0, 0])
		self.app.lamp = 0;
		log(self.app.lamp)
		return 'off'

class SleepMonitorApp:
    def startGstreamerVideo(self):

        videosrc = '/dev/video0'

        try:
            out = subprocess.check_output(['v4l2-ctl', '--list-devices'])
        except subprocess.CalledProcessError as e:
            out = e.output

        lines = out.splitlines()
        for (idx, line) in enumerate(lines):
            if 'bcm2835' in line:
                nextline = lines[idx + 1]
                videosrc = nextline.strip()

        spawnNonDaemonProcess(reactor, LoggingProtocol('gstream-video'), '/bin/sh',
                              ['sh', 'gstream_video.sh', videosrc])

        log('Started gstreamer video using device %s' % videosrc)

    def __init__(self):
        queues = []

        json_data = {'peak' : -10, 'peak_max' : -10}

        with io.open('web/js/vol_data.json', 'w', encoding='utf8') as outfile:
            str_ = json.dumps(json_data, indent=4, sort_keys=True, separators=(',', ': '), ensure_ascii=False)
            outfile.write(unicode(str_))

        spawnNonDaemonProcess(reactor, LoggingProtocol('sheep'), '/bin/sh',
                              ['sh', 'sheep_init.sh'])

        self.strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL, LED_STRIP)
    	# Intialize the library (must be called once before other functions).
    	self.strip.begin()
        self.strip.show()

        self.config = Config()
        self.reactor = reactor

        self.sheepWatching = 0
        self.sheepPlaying = 0

        self.lamp = 0

        self.oximeterReader = OximeterReader(self)
        self.temp = 0

        self.motionDetectorStatusReader = MotionDetectionStatusReaderProtocol(self)
        spawnNonDaemonProcess(reactor, self.motionDetectorStatusReader, 'python',
                              ['python', 'MotionDetectionServer.py'])
        log('Started motion detection process')

        self.influxLogger = InfluxLoggerClient()
        spawnNonDaemonProcess(reactor, self.influxLogger, 'python',
                              ['python', 'InfluxDbLogger.py'])
        log('Started influxdb logging process')

        logger = Logger(self)
        logger.run()
        log('Started logging')

        factory = protocol.Factory()
        factory.protocol = JpegStreamReader
        factory.queues = queues
        factory.latestImage = None
        reactor.listenTCP(9999, factory)
        log('Started listening for MJPEG stream')

        root = File('web')
        root.putChild('stream.mjpeg', MJpegResource(queues))
        root.putChild('latest.jpeg', LatestImageResource(factory))
        root.putChild('status', StatusResource(self))
        root.putChild('ping', PingResource())
        root.putChild('getConfig', GetConfigResource(self))
        root.putChild('updateConfig', UpdateConfigResource(self))

        # added
        root.putChild('getTemp', GetTemp(self))
        root.putChild('playMusic', PlayMusic(self))
        root.putChild('stopMusic', StopMusic(self))
        root.putChild('toggleSheep', ToggleSheep(self))
        root.putChild('toggleLamp', ToggleLamp(self))
        root.putChild('setSheep', SetSheep(self))
        root.putChild('forceLampOn', ForceLampOn(self))
        root.putChild('forceLampOff', ForceLampOff(self))
        root.putChild('forceSound', ForceMusic(self))

        sslContext = ssl.DefaultOpenSSLContextFactory(
			'/home/pi/ssl/privkey.pem',
			'/home/pi/ssl/cacert.pem',
			)

        site = server.Site(root)
        #PORT = 443
        PORT = 80
        #BACKUP_PORT = 80
        BACKUP_PORT = 8080

        portUsed = PORT
        try:
            reactor.listenTCP(PORT, site)
            log('Started webserver at port %d' % PORT)
            #reactor.listenSSL(
				#PORT, # integer port
				#site, # our site object, see the web howto
				#contextFactory = sslContext,
			#)
        except twisted.internet.error.CannotListenError:
            portUsed = BACKUP_PORT
            reactor.listenTCP(BACKUP_PORT, site)
            log('Started webserver at port %d' % BACKUP_PORT)

        startZeroConfServer(portUsed)

        startAudio()		#IfAvailable()


        reactor.run()

    def resetAfterConfigUpdate(self):
        log('Updated config')
        self.config.write()
        self.oximeterReader.reset()
        self.motionDetectorStatusReader.reset()
        log(self.temp)
        # update light settings - toggle lamp variable then trigger toggleLamp()

if __name__ == "__main__":
    import logging
    setupLogging()
    log('Starting main method of sleep monitor')
    try:
        app = SleepMonitorApp()
    except:  # noqa: E722 (OK to use bare except)
        logging.exception("main() threw exception")
