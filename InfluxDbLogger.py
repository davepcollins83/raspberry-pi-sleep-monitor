#!/usr/bin/env python

from twisted.internet import reactor, stdio
from twisted.protocols import basic

from datetime import datetime, timedelta
from influxdb import InfluxDBClient

import json
import io

HOST = "localhost"
PORT = 9001
USER = "pi"
PASSWORD = "pi"
DB_NAME = "sleep_monitor"

class ProcessInput(basic.LineReceiver):
    # This seemingly unused line is necessary to over-ride the delimiter
    # property of basic.LineReceiver which by default is '\r\n'. Do not
    # remove this!
    from os import linesep as delimiter

    def __init__(self, client):
        self.client = client
        self.session = 'production'
        self.runNo = datetime.utcnow().strftime('%Y%m%d%H%M')
        self.lastLogTime = datetime.min

        self.lastSpo2 = -1
        self.lastBpm = -1
        self.lastMotion = 0
        self.lastAlarm = 0

    def shouldLog(self, time, spo2, bpm, motion, alarm):
        if spo2 != self.lastSpo2:
            return True
        if bpm != self.lastBpm:
            return True
        if motion != self.lastMotion:
            return True
        if alarm != self.lastAlarm:
            return True
        if (time - self.lastLogTime) > timedelta(seconds=30):
            return True

        return False

    def lineReceived(self, line):
        nums = [int(s) for s in line.split()]
        (spo2, bpm, motion, alarm, temp) = nums

		#log(nums)

        time = datetime.utcnow()

        peak_max = 0
        peak_float = 0

        if self.shouldLog(time, spo2, bpm, motion, alarm):

            with open('web/js/vol_data.json') as data_file:
                data_loaded = json.load(data_file)

        	peak_max = data_loaded['peak_max']
            peak_float = data_loaded['peak']

            peak_int = int(100 * (5-peak_max))

            json_data = {'peak' : peak_float, 'peak_max' : -10}

            with io.open('web/js/vol_data.json', 'w', encoding='utf8') as outfile:
                str_ = json.dumps(json_data, indent=4, sort_keys=True, separators=(',', ': '), ensure_ascii=False)
                outfile.write(unicode(str_))

        	json_body = [{
                "measurement": self.session,
                "tags": {
                    "run": self.runNo,
                },
                "time": time.ctime(),
                "fields": {
                    "spo2": spo2,
                    "bpm": bpm,
                    "motion": motion,
                    "alarm": alarm,
                    "audio": peak_int,
                    "temp": temp
                }
            	}]

                self.client.write_points(json_body)
                self.lastLogTime = time
                #check

        self.lastSpo2 = spo2
        self.lastBpm = bpm
        self.lastMotion = motion
        self.lastAlarm = alarm

def createInfluxClient():
    client = InfluxDBClient(HOST, PORT, USER, PASSWORD, DB_NAME)

    dbs = client.get_list_database()
    for db in dbs:
        if db['name'] == DB_NAME:
            break
    else:
        client.create_database(DB_NAME)

    return client

def main():
    client = createInfluxClient()
    stdio.StandardIO(ProcessInput(client))
    reactor.run()

if __name__ == "__main__":
    main()
