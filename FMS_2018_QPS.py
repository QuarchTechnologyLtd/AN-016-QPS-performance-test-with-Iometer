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
2- Install quarchpy, wmi (https://github.com/mhammond/pywin32/releases) and pywin32
3- On startup, select the drive you wish to test

####################################
'''

# Import modules and packages.
from __future__ import division
from sys import argv

import time
import signal
import datetime
from time import mktime
import multiprocessing as mp
from multiprocessing import Pipe

try:
    # for Python 2.x
    import thread
except ImportError:
    # for Python 3.x
    import _thread

import os
import shutil

import math
import re
import mmap

try:
    # for Python 2.x
    from StringIO import StringIO
except ImportError:
    # for Python 3.x
    from io import StringIO

from quarchpy import generateIcfFromCsvLineData, readIcfCsvLineData, requiredQuarchpyVersion, generateIcfFromConf, quarchDevice, quarchQPS, isQpsRunning, startLocalQps, closeQPS, qpsInterface, GetDiskTargetSelection, GetQpsModuleSelection, runIOMeter, processIometerInstResults, adjustTime

filePath = os.path.dirname(os.path.realpath(__file__))

'''
The main function sets up the tests and then invokes Iometer, QPS and the results reading thread which reads
the data back from the IOmeter results file
'''
def main():
        
        # Setup the callback dictionary, used later to notify us of data needing processed.
        # If you don't want to implement all the functions, just delete the relevant item
        iometerCallbacks = {
            "TEST_START": notifyTestStart,
            "TEST_END": notifyTestEnd,
            "TEST_RESULT": notifyTestPoint,
        }

        # Check that the installed version of quarchpy is at the required minimum level
        if not requiredQuarchpyVersion ("1.3.4"):
            raise ValueError ("quarchpy reported version is not new enough for this script!")

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
            # Start the version on QPS installed with the quarchpy, otherwise use the running version
            startLocalQps(keepQisRunning=True)

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
        print ("MODULE CONNECTED: \n" + myQpsDevice.sendCommand ("*idn?"))

        # Setup the voltage mode and enable the outputs
        setupPowerOutput (myQpsDevice)
        # Sleep for a few seconds to let the drive target enumerate
        time.sleep(5)
        
        '''
        *****
        Get the user to select a valid target drive
        *****
        '''
        targetInfo = GetDiskTargetSelection ()               
        
        print ("\n TARGET DEVICE: " + targetInfo["NAME"])
        print (" VOLUME: " + targetInfo["DRIVE"])
        
        # Run from CSV settings or all the files in /conf        
        try:
            run_option = raw_input ("\n1 - Use settings in CSV file\n2 - Run all files in /conf\n>>> Please select a mode: ")
        except NameError:
            run_option = input ("\n1 - Use settings in CSV file\n2 - Run all files in /conf\n>>> Please select a mode: ")
        
        if "1" in run_option:
            keepReading = True
            count = 1
            confDir = os.getcwd() + "\\conf\\temp_conf"
            tempList = []
            while 1:
                csvData, keepReading = readIcfCsvLineData("csv_example.csv", count)
                if not keepReading:
                    break
                timeStamp = time.strftime("%Y-%m-%d-%H-%M-%S", time.gmtime())        
                icfFilePath = confDir + "\\" + "file" + str(count) +"_"+ timeStamp + ".icf"
                tempList.append(icfFilePath)
                generateIcfFromCsvLineData(csvData, icfFilePath, targetInfo)
                count += 1
               
        if "2" in run_option:
            confDir = os.getcwd() + "\\conf"
            generateIcfFromConf(confDir, targetInfo)

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
        myStream = myQpsDevice.startStream (filePath + "\\" + fileName)

        # Create new custom channels to plot IO results
        myStream.createChannel ('I/O', 'IOPS', 'IOPS', "Yes")
        myStream.createChannel ('Data', 'Data', 'Bytes', "Yes")
        myStream.createChannel ('Response', 'Response', 'mS', "No")
        
        # Delete any old output files
        if os.path.exists("testfile.csv"):
            os.remove("testfile.csv")
        if os.path.exists("insttestfile.csv"):
            os.remove("insttestfile.csv")

        # Execute every ICF file in sequence and process them. Deletes any temporary ICF
        executeIometerFolderIteration (confDir, myStream, iometerCallbacks)
        
        # Deletes temporary files
        try:
            for tempFile in tempList:
                os.remove(tempFile) 
        except NameError:
            pass
        
        # End the stream after a few seconds of idle
        time.sleep(5)
        myStream.stopStream()
   
 
'''
Executes a group of .ICF files in the given folder and processes the results into the current stream
'''
def executeIometerFolderIteration (confDir, myStream, userCallbacks):
    skipFileLines = 0
        
    for file in os.listdir(confDir):
        if file.endswith(".icf"):
                
            icfFilePath = os.path.join(confDir, file)
            icfFilePath = "\"" + icfFilePath + "\""

            # Start up IOmeter and the results parser
            threadIometer = mp.Process(target=runIOMeter, args = (icfFilePath,))
                
            # Start both threads. 
            threadIometer.start()

            skipFileLines = processIometerInstResults(file, skipFileLines, myStream, userCallbacks)
                
            # Wait for threads to complete
            threadIometer.join()

            time.sleep(5)
         
'''
Function to check the output state of the module and prompt to select an output mode if not set already
'''
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


'''
*****
The following functions are callbacks from the Iometer parsing code, notifying us of new actions or data, so we can
act on it in a custom way (generally adding it to the QPS chart)
*****
'''

'''
Callback: Run to add the start point of a test run.  Adds an annotation to the chart
'''
def notifyTestStart (myStream, timeStamp, testDescription):
    myStream.addAnnotation(testDescription + "\\n TEST STARTED", adjustTime(timeStamp))

'''
Callback: Run to add the end point of a test run.  Adds an annotation to the chart and 
ends the current block of performance data
'''
def notifyTestEnd (myStream, timeStamp, testName):
    # Add an end annotation
    myStream.addAnnotation("END", adjustTime(timeStamp))
    # Terminate the sequence of user data just after the current time, to avoid spanning the chart across the idle area
    myStream.addDataPoint('I/O', 'IOPS', "endSeq", adjustTime(timeStamp)+0.01)
    myStream.addDataPoint('Data', 'Data', "endSeq", adjustTime(timeStamp)+0.01)
    myStream.addDataPoint('Response', 'Response', "endSeq", adjustTime(timeStamp)+0.01)

'''
Callback: Run for each test point to be added to the chart
'''
def notifyTestPoint (myStream, timeStamp, dataValues):
    # Add each custom data point that has been passed through
    # TODO: adjustTime should not be needed here!  All times in out python code should be standard python time stamps.  Any conversion should be done at source (reading from Iometer) or output (sendint the final command to the module)
    if (dataValues.has_key ("IOPS")):
        myStream.addDataPoint('I/O', 'IOPS', dataValues["IOPS"], adjustTime(timeStamp))
    if (dataValues.has_key ("DATA_RATE")):
        myStream.addDataPoint('Data', 'Data', dataValues["DATA_RATE"], adjustTime(timeStamp))
    if (dataValues.has_key ("RESPONSE_TIME")):
        myStream.addDataPoint('Response', 'Response', dataValues["RESPONSE_TIME"], adjustTime(timeStamp))    


# Calling the main () function
if __name__=="__main__":
    main()