# !/usr/bin/python

import sys, os
import gi
gi.require_version('Gst', '1.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gst, GObject, Gtk
import json
import io

class Main:
    def __init__(self):

	gain = 1
	peak_max = -500



	self.pipeline = Gst.Pipeline.new("mypipeline")

	source = Gst.ElementFactory.make("alsasrc", "alsa-src")
	source.set_property("device", "plug:dmic_sv")

	caps = Gst.Caps.from_string('audio/x-raw,channels=2,layout="interleaved",rate=16000,format="S16LE"')
	filter = Gst.ElementFactory.make("capsfilter", "filter")
	filter.set_property("caps", caps)

	audioamplify = Gst.ElementFactory.make("audioamplify", "audio-amplify")
	audioamplify.set_property("amplification", gain)



	level = Gst.ElementFactory.make("level", "level")
	level.set_property("message", "true")
	#level.set_property("interval", 1000000)

	opusenc = Gst.ElementFactory.make("opusenc", "opus-enc")
	opusenc.set_property("bitrate", 20000)

	rtpopus = Gst.ElementFactory.make("rtpopuspay", "rtp-opus-pay")

	sink = Gst.ElementFactory.make("udpsink", "udp-sink")
	sink.set_property("host", "127.0.0.1")
	sink.set_property("port", 5002)

	self.pipeline.add(source)
	self.pipeline.add(filter)
	self.pipeline.add(audioamplify)
	self.pipeline.add(level)
	self.pipeline.add(opusenc)
	self.pipeline.add(rtpopus)
	self.pipeline.add(sink)


	source.link(filter)
	filter.link(audioamplify)
	audioamplify.link(level)
	level.link(opusenc)
	opusenc.link(rtpopus)
	rtpopus.link(sink)

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

        self.pipeline.set_state(Gst.State.PLAYING)

    def on_message(self, bus, message):
		t = message.type
		if t == Gst.MessageType.ERROR:
			self.pipeline.set_state(Gst.State.NULL)
			err, debug = message.parse_error()
			print "Error: %s" % err, debug


		peak_float = -500
		
		if t == Gst.MessageType.ELEMENT:

			s = message.get_structure()
			peak = s.get_value("peak")
			
			peak_float = float(peak[0])
			
			print peak_float
			
			#with open('web/js/vol_data.json') as data_file:
				#data_loaded = json.load(data_file)
    			
    		json_data = {'peak' : peak_float}
    		
    		with io.open('web/js/vol_data.json', 'w', encoding='utf8') as outfile:
    			str_ = json.dumps(json_data, indent=4, sort_keys=True, separators=(',', ': '), ensure_ascii=False)
    			outfile.write(unicode(str_))
		

	
Gst.init(None)
start=Main()
Gtk.main()
