#!/usr/bin/env python
'''
FLS2018 Demo
This example uses IOMeter and QPS to run traffic tests to a drive, with the power and performance data displayed.

- The user is prompted to select n IOmeter target (Physical disk or drive letter)
- The .conf files are IOmeter templates which are then turned into .icf files with the selected target in place
- IOmeter is invoked over each .icf file in the folder whild QPS is used to display combined power and performance data

########### VERSION HISTORY ###########

27/06/2018 - Andy Norrie    - First version, based on initial work from Nikolas Ioannides
02/08/2018 - Pedro Leao		- Updated to add nicer selection screens and IOmeter control

########### INSTRUCTIONS ###########

1- Connect a Quarch power module to your PC via USB or LAN
2- Install quarchpy, wmi and pywin32
3- On startup, select the drive you wish to test

####################################
'''

# Import modules and packages.
from __future__ import division
from sys import argv

import time
#import serial
import sys
import signal
import datetime
from time import mktime

try:
    # for Python 2.x
    import thread
except ImportError:
    # for Python 3.x
    import _thread

import os
import shutil
import subprocess
import re
import csv
import threading
import multiprocessing as mp
from multiprocessing import Pipe
import math
import wmi
import re
import mmap

try:
    # for Python 2.x
    from StringIO import StringIO
except ImportError:
    # for Python 3.x
    from io import StringIO

#Import for getAvailableDrives function
import win32file, win32api
from subprocess import check_output

from quarchpy import quarchDevice, quarchQPS, isQpsRunning, startLocalQps, closeQPS, qpsInterface

filePath = os.path.dirname(os.path.realpath(__file__))

'''
The main function sets up the tests and then invokes Iometer, QPS and the results reading thread which reads
the data back from the IOmeter results file
'''
def main():

        # Display title text
        print ("\n################################################################################")
        print ("\n                           QUARCH TECHNOLOGY                        \n\n  ")
        print ("Automated power and performance data acquisition with Quarch Power Studio.   ")
        print ("\n################################################################################\n")        
    
        '''
        *****
        First we activate QIS and prompt the user to select a power module
        *****
        '''
        # Checks is QPS is running on the localhost
        if not isQpsRunning():
            # Start the version on QPS installed with the quarchpy, Otherwise use the running version
            startLocalQps()

        # Open an interface to local QPS
        myQps = qpsInterface()        

        # Get the user to select the module to work with
        myDeviceID = GetQpsModuleSelection (myQps)

        # Create a Quarch device connected via QPS
        myQuarchDevice = quarchDevice (myDeviceID, ConType = "QPS")
        # Upgrade Quarch device to QPS device
        myQpsDevice = quarchQPS(myQuarchDevice)
        myQpsDevice.openConnection()

        # Prints out connected module information
        print ("\n MODULE: " + myQpsDevice.sendCommand ("hello?")) 
        print (" SERIAL: " + myQpsDevice.sendCommand ("*enclosure?"))

        # Setup the voltage mode and enable the outputs
        setupPowerOutput (myQpsDevice)

        '''
        *****
        Get the user to select a valid target drive
        *****
        '''
        targetInfo = GetDiskTargetSelection ()               
        
        print ("\n TARGET DEVICE: " + targetInfo[0])
        print (" VOLUME: " + targetInfo[1])

        '''
        *****
        Setup and begin streaming
        *****
        '''
        
        # Get the required averaging rate from the user.  This sets the resolution of data to record        
        try:
            averaging = raw_input ("\n>>> Enter the average rate [32k]: ") or "32k"
        except NameError:
            averaging = input ("\n>>> Enter the average rate [32k]: ") or "32k"        

        # Set the averaging rate to the module
        myQpsDevice.sendCommand ("record:averaging " + averaging)

        # Start a stream, using the local folder of the script and a time-stamp file name in this example
        fileName = time.strftime("%Y-%m-%d-%H-%M-%S", time.gmtime())        
        main.myStream = myQpsDevice.startStream (filePath + fileName)

        # Create new custom channels to plot IO results
        main.myStream.createChannel ('I/O', 'IOPS', 'IOPS', "Yes")
        main.myStream.createChannel ('Data', 'Data', 'Bytes', "Yes")
        main.myStream.createChannel ('Response', 'Response', 'us', "Yes")
        
        # Delete any old output files
        if os.path.exists("testfile.csv"):
            os.remove("testfile.csv")
        if os.path.exists("insttestfile.csv"):
            os.remove("insttestfile.csv")

        # If .icf files are found in the test configuration folder, to describe the test to run
        confDir = os.getcwd() + '\conf'        
          
        # Execute every ICF file in sequence and process them
        executeIometerFolderIteration (confDir)

        # TODO: Add an option to parse a .csv file with IOmeter options inside, and use this to generate full .ICF files

        # End the stream after a few seconds of idle
        time.sleep(5)
        main.myStream.stopStream()
        
        #sys.exit ()        
     
 
'''
Executes a group of .ICF files in the given folder and processes the results into the current stream
'''
def executeIometerFolderIteration (confDir, myStream):
    skipFileLines = 0
        
    for file in os.listdir(confDir):
        if file.endswith(".icf"):
                
            icfFilePath = os.path.join(confDir, file)

            # Start up IOmeter and the results parser
            threadIometer = mp.Process(target=runIOMeter, args = (icfFilePath,))
                
            # Start both threads. 
            threadIometer.start()

            skipFileLines = processIometerInstResults(file, skipFileLines, myStream)
                
            # Wait for threads to complete
            threadIometer.join()

            time.sleep(5)

'''
Run to add the start point of a test run.  Adds an annotation to the chart
'''
def notifyTestStart (timeStamp, testName):
    return Null

'''
Run to add the end point of a test run.  Adds an annotation to the chart and 
ends the current block of performance data
'''
def notifyTestEnd (timeStamp, testName):
    return Null

'''
Run for each test point to be added to the chart
'''
def notifyTestPoint (timeStamp, dataValue):
    return Null
         

def setupPowerOutput (myModule):

    # Output mode is set automatically on HD modules using an HD fixture, otherwise we will chose 5V mode for this example
    if "DISABLED" in myModule.sendCommand("config:output Mode?"):
        try:
            drive_voltage = raw_input("\n Either using an HD without an intelligent fixture or an XLC.\n \n>>> Please select a voltage [3V3]: ") or "3V3"
        except NameError:
            drive_voltage = input("\n Either using an HD without an intelligent fixture or an XLC.\n \n>>> Please select a voltage [3V3]: ") or "3V3"

        myModule.sendCommand("config:output:mode:"+ drive_voltage)
    
    # Check the state of the module and power up if necessary
    powerState = myModule.sendCommand ("run power?")
    # If outputs are off
    if "OFF" in powerState:
        # Power Up
        print ("\n Turning the outputs on:"), myModule.sendCommand ("run:power up"), "!"


# Calling the main () function
if __name__=="__main__":
    main()










