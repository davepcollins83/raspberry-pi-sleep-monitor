#!/bin/sh

kill $(ps aux | grep '[a]play' | awk '{print $2}')

