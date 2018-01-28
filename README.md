# A baby sleep monitor using a Raspberry Pi

This setup shows how to create a baby sleep monitor which is able to stream a low latency image stream from a Raspberry Pi to a computer.

Browse the [Wiki page](https://github.com/srinathava/raspberry-pi-sleep-monitor/wiki) for instructions on setup and usage.

Additional Setup steps:

<br>sudo apt-get install gstreamer1.0-plugins-good gst-python-1.0 gst-alsa pulseaudio
<br>sudo apt-get install python-pip3
<br>sudo pip install Jinja2
<br>sudo pip install pyglet
<br>
<br>Detailed steps from https://learn.adafruit.com/adafruit-max98357-i2s-class-d-mono-amp?view=all#raspberry-pi-usage
<br>
<br>Comment out snd_bcm2835 in /etc/modules
<br>
<br>Added recommended lines to .asoundrc and asound.conf
<br>
<br>Changed config.txt to:
<br>#dtparam=audio=on			-	disabled
<br>start_x=1
<br>gpu_mem=128
<br>dtoverlay=w1-gpio
<br>dtoverlay=hifiberry-dac		-	added
<br>dtoverlay=i2s-mmap			-	added

