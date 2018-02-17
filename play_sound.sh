#!/bin/sh

if pgrep -x "mpg123" > /dev/null
then
	kill $(ps aux | grep '[m]pg123' | awk '{print $2}')
else
	mpg123 /media/noise.mp3
fi
