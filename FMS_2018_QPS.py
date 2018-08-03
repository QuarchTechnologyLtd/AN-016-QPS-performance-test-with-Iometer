#!/usr/bin/env python
'''
FLS2018 Demo
This example uses IOMeter and QPS to run traffic tests to a drive, with the power and performance data displayed.

- The user is prompted to select n IOmeter target (Physical disk or drive letter)
- The .conf files are IOmeter templates which are then turned into .icf files with the selected target in place
- IOmeter is invoked over each .icf file in the folder whild QPS is used to display combined power and performance data

########### VERSION HISTORY ###########

27/06/2018 - Andy Norrie    - First version, based on initial work from Nikolas Ioannides

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
        print ("\n################################################################################")
        print ("\n                           QUARCH TECHNOLOGY                        \n\n                                FMS2018                             \n\n  Automated power and performance data acquisition with Quarch Power Studio.   ")
        print ("\n################################################################################\n")
        ################################################
        ## QUARCH MODULE SELECTION #####################
        ################################################  
    
        # Checks is QPS is running on the localhost
        if not isQpsRunning():
            # Start the version on QPS installed with the quarchpy, Otherwise use start
            startLocalQps()

        myQps = qpsInterface()

        # Request a list of all USB and LAN accessible modules
        devList = myQps.getDeviceList()

        # Print the devices, so the user can choose one to connect to
        print ("\n ########## STEP 1 - Select a Quarch Module. ########## \n")
        print (' ----------------------------------')
        print (' |  {:^5}  |  {:^20}|'.format("INDEX", "MODULE"))
        print (' ----------------------------------')
        
        for idx in xrange(len(devList)):
            print (' |  {:^5}  |  {:^20}|'.format(str(idx+1), devList[idx]))
            print(' ----------------------------------')

        ## Get the user to select the device to control
        try:
            moduleId = int(raw_input ("\n>>> Enter the index of the Quarch module: "))
        except NameError:
            moduleId = int(input ("\n>>> Enter the index of the Quarch module: "))

        myDeviceID = devList[moduleId-1]

        # Create a Quarch device connected via QPS
        myQuarchDevice = quarchDevice (myDeviceID, ConType = "QPS")

        # Upgrade Quarch device o QPS device
        myQpsDevice = quarchQPS(myQuarchDevice)

        ## Prints out connected module information
        print ("\n MODULE: " + myQpsDevice.sendCommand ("hello?")) 
        print (" SERIAL: " + myQpsDevice.sendCommand ("*enclosure?"))

        ## Setup the voltage mode and enable the outputs
        setupPowerOutput (myQpsDevice)

        ## Set the averaging rate for the module.  This sets the resolution of data to record
        ## This is done via a direct command to the power module
        try:
            averaging = raw_input ("\n>>> Enter the average rate [32k]: ") or "32k"
        except NameError:
            averaging = input ("\n>>> Enter the average rate [32k]: ") or "32k"
        
        
        ################################################
        ## DISK SELECTION ##############################
        ################################################
    
        # Get available physical disks
        diskList = getAvailableDisks ("OS")
        # Get available mapped drives
        driveList = getAvailableDrives ()

        deviceList = driveList + diskList

        # Print selection dialog

        print ("\n\n ########## STEP 2 = Select a target drive. ##########\n")
        print (' -------------------------------------------------------------')
        print (' |  {:^5}  |  {:^6}  |  {:^35}  |'.format("INDEX", "VOLUME", "DESCRIPTION"))
        print (' -------------------------------------------------------------')

        for i in deviceList:
            print (' |  {:^5}  |  {:^6}  |  {:^35}  |'.format(str(deviceList.index(i)+1), i[1], i[0]))
            print(' -------------------------------------------------------------')

        try:
            drive_index = int(raw_input("\n>>> Enter the index of the target device: " )) - 1
        except NameError:
            drive_index = int(input("\n>>> Enter the index of the target device: ")) - 1

        try:
            deviceInfo = deviceList[drive_index]
            1/(drive_index+1)
        except:
            raise Exception("Invalid option - please select another drive!")
        
		
        print ("\n TARGET DEVICE: " + deviceInfo[0])
        print (" VOLUME: " + deviceInfo[1])



        ################################################
        ## START STREAM ################################
        ################################################ 
        
        myQpsDevice.openConnection()

        time.sleep(3)
        myQpsDevice.sendCommand ("record:averaging " + averaging)

        ## Start a stream, using the local folder of the script and a time-stamp file name in this example
        fileName = time.strftime("%Y-%m-%d-%H-%M-%S", time.gmtime())
        
        main.myStream = myQpsDevice.startStream (filePath + fileName)

        main.myStream.createChannel ('I/O-1', 'SpeedIO', 'io/s', "Yes")
        main.myStream.createChannel ('Data-1', 'Data', 'B/s', "Yes")

        ################################################
        ## START I/OMETER ##############################
        ################################################ 

        # Delete any old output files
        if os.path.exists("testfile.csv"):
            os.remove("testfile.csv")
        if os.path.exists("insttestfile.csv"):
            os.remove("insttestfile.csv")


        # Create the ICF files needed for this run
        confDir = os.getcwd() + '\conf'
        main.fileCount, main.config_list = setupIometerFiles (confDir, deviceInfo)
        main.fileIte = 0
        
        skipFileLines = 0
        
        for file in os.listdir(confDir):
            if file.endswith(".icf"):
                
                icfFilePath = os.path.join(confDir, file)

                # Start up IOmeter and the results parser
                threadIometer = mp.Process(target=runIOMeter, args = (icfFilePath,))
                
                # Start both threads. 
                threadIometer.start()

                skipFileLines = processIometerInstResults(file, skipFileLines)
                main.fileIte += 1
                
                # Wait for threads to complete TODO: May need changes here depending on new results parser
                threadIometer.join()

                time.sleep(5)

        time.sleep(3)
        main.myStream.addAnnotation("DRIVE IDLE")
        time.sleep(15)
        main.myStream.addAnnotation("TEST ENDED")

        

        main.myStream.stopStream()
        
        #sys.exit ()        
     
 


 
'''
Gets a list of available host drive, excluding the one the host os running on if specified
'''
def getAvailableDisks (hostDrive):
    driveList = []
    diskNum = 0

    diskScan = wmi.WMI()

    # Loop through disks
    for disk in diskScan.Win32_diskdrive(["Caption", "DeviceID", "FirmwareRevision"]):        
        DiskInfo= str(disk)
                
        # Try to get the disk caption
        DiskInfo.strip()
        a = re.search('Caption = "(.+?)";', DiskInfo)    
        if a:
            diskName = a.group(1)
           
        # Try to get the disk ID
        b = re.search('PHYSICALDRIVE(.+?)";', DiskInfo)
        if b:
            diskId = b.group(1)         
        # Try to get the disk FW
        c = re.search('FirmwareRevision = "(.+?)";', DiskInfo)
        if c:
            diskFw = c.group(1)           

        # Skip if this is our host drive!
        if (diskName != hostDrive):
            # Append drive info to array
            driveList.append ([])
            driveList[diskNum].append (str(diskName))
            driveList[diskNum].append (str(diskId))            
            driveList[diskNum].append (str(diskFw))        
            diskNum = diskNum + 1

    # Return the list of drives
    return driveList

def remove_values_from_list(the_list, val):
   return [value for value in the_list if value != val]
   
def getAvailableDrives():

    #return string of logicaldisks' specified attributes
    RList = check_output( "wmic logicaldisk get caption, Description" )

    #decode if python version 3
    if sys.version_info.major==3:
        RList = str( RList, "utf-8" )

    #split into readable items
    RList_Lines = RList.split("\n")

    RList_MinusNetwork = []

    #appaend all drives to list that are not network drives
    for item in RList_Lines:
        if "Network Connection" not in item:
            if len(item) > 0:
                RList_MinusNetwork.append(item[0:item.find("  ")])

    #remove column headers
    del RList_MinusNetwork[0]

    #function call to remove every occurance of \r in list
    RList_MinusNetwork = remove_values_from_list(RList_MinusNetwork, "\r")

    RL_DrivesAndVolumeInfo = []

    #call function to return volume name of each drive (if available)
    for i in RList_MinusNetwork:
        i.replace(":", "://")
        try:
            RL_DrivesAndVolumeInfo.append(win32api.GetVolumeInformation(i)[0])
            RL_DrivesAndVolumeInfo.append(i)
            time.sleep(0.1)
        except:
            continue
        
    returnList = []

    for i in xrange(0, len(RL_DrivesAndVolumeInfo), 2):
       returnList.append([RL_DrivesAndVolumeInfo[i], RL_DrivesAndVolumeInfo[i+1], "Null"])
        
 
        
    currentDrive = os.path.abspath(os.sep)

    for i in returnList:
        for j in i:
            if currentDrive in j:
                returnList.remove(currentDrive)
    
    return returnList

'''
Scans the given path for .conf files (ioMeter ICF files with no target) and
creates .ICF files with the correct drive target information in place
'''
def setupIometerFiles(confPath, driveInfo):

    configFiles = []
    fileCount = 0
    
    config_list = []
    
    # Scan through .conf files
    for file in os.listdir(confPath):
        if file.endswith(".conf"):
        
            confFilePath = os.path.join(confPath, file)
            icfFilePath = confFilePath.replace ('.conf', '.icf')

            # Delete any old ICF file
            if os.path.exists(icfFilePath):
                os.remove(icfFilePath)        

            # Open the .conf file
            openFile = open (confFilePath)
            fileData = openFile.read ()
            openFile.close ()
   
            # Create the string modifications needed to set the correct target
            newStr = "'Target assignments\n'Target\n\t" + str(driveInfo[1]) +  ": \"" + str(driveInfo[0]) + " " + str(driveInfo[2]) + "\"" + "\n'Target type\n\tDISK\n'End target\n'End target assignments"  
            oldStr = "\'Target assignments\n\'End target assignments"
            # Replace the string
            fileData = fileData.replace(str(oldStr),str(newStr))

            # Write the text out to the final ICF file
            openFile = open (icfFilePath, 'a+')
            openFile.write (fileData)

            s = mmap.mmap(openFile.fileno(), 0, access=mmap.ACCESS_READ)
            pos_start = s.find('Assigned access specs')
            pos_end = s.find('End assigned access specs')
            if pos_start != -1:
                config_list.append(s[pos_start+21:pos_end-1])

            openFile.close ()
            
            # Increment file counter
            fileCount = fileCount + 1

    return fileCount, config_list

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
    
'''
This function is called in a seperate thread and runs the Iometer process, using the given file name to
describe the tests to be carried out
'''
def runIOMeter(fileName):
    time.sleep(1)
    #print ("Calling IOMETER with: " + fileName)
    info = subprocess.STARTUPINFO()
    info.dwFlags = 1
    info.wShowWindow = 0

    runAsAdminCmd = "runas"
    
    proc = subprocess.Popen("IOmeter.exe /c "  + fileName + " /r testfile.csv", stdout = subprocess.PIPE, stderr = subprocess.PIPE, startupinfo=info)

    out, error = proc.communicate()
    #print out, error
    
'''
Allows the given file to be iterated through, using a python 'generator'
'''
def followResultsFile (theFile):
    #thefile.seek(0,2)
    while True:
        line = theFile.readline()
        if not line:
            time.sleep(0.1)
            continue
        yield line

'''
This is called in a seperate thread and runs in parallel with Iometer, pulling the results
out of the 'inst' results file and passing them for processing.
We read the file to locate: Start, Data and End
'''


def adjustTime(timestamp):
    return time.mktime(datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S:%f").timetuple())

def processIometerInstResults(testName, skipFileLines):
    
    testAnnotation = main.config_list[main.fileIte]
    testAnnotation = re.sub(r"\s+", " ", testAnnotation)
    testAnnotation = testAnnotation.replace(";", "\\n")
    testAnnotation = testAnnotation.replace("(", "")
	
    driveSpeed = ""
    fileSection = 0
        
    # Wait for the file to exist
    #print ("Waiting for results file...")
    while(os.path.isfile("insttestfile.csv") == False): pass

    # Open the file for non-exclusive read
    resultsFile = open("insttestfile.csv", 'rb')
    # Attach the file iterator
    resultsIterator = followResultsFile (resultsFile)
    
    lineCount = 0
    lineCount2 = 0
    #average data across points
    sum_all_threads1 = 0
    sum_all_threads2 = 0
    
    for dataLine in resultsIterator:
        f = StringIO (dataLine.decode ('utf-8'))
        lineCount = lineCount + 1           

        if( lineCount < skipFileLines ):
            continue

        skipFileLines = skipFileLines + 1

        csvData = list(csv.reader (f))
        
        if (fileSection == 0 and csvData[0][0] != '\'Time Stamp'):            
            continue
        elif (fileSection == 0): 
            fileSection = 1
            continue

        if (fileSection == 1):            
            timeStamp =  csvData[0][0]
            #print ("TEST STARTED AT " + timeStamp)
           
          
            main.myStream.addAnnotation(testAnnotation + "\\n TEST STARTED", adjustTime(timeStamp))

            fileSection = 2
            continue        

        if (fileSection == 2 and csvData[0][0] != 'TimeStamp'):            
            continue
        elif (fileSection == 2): 
            fileSection = 3
            continue

        if (fileSection == 3):
            lineCount2 += 1
            timeStamp =  csvData[0][0]
            if (timeStamp == '\'Time Stamp'):
                fileSection = 4
                continue
            dataValue1 = csvData[0][7]
            dataValue2 = csvData[0][13]
            
            sum_all_threads1 += float(dataValue1)
            sum_all_threads2 += float(dataValue2)
            
            if (lineCount2 % 8 == 0):
                
                sum_all_threads1 = sum_all_threads1
                sum_all_threads2 = sum_all_threads2*1000000
				
                main.myStream.addDataPoint('I/O-1', 'SpeedIO', sum_all_threads1, adjustTime(timeStamp))
                main.myStream.addDataPoint('Data-1', 'Data', sum_all_threads2, adjustTime(timeStamp))
                
                sum_all_threads1 = 0
                sum_all_threads2 = 0
                
            #print ('LOG ' + timeStamp + " " + dataValue)
            #main.myStream.addDataPoint('I/O-1', 'SpeedIO', dataValue1, adjustTime(timeStamp))
            #main.myStream.addDataPoint('Mb-1', 'SpeedMb', dataValue2, adjustTime(timeStamp))

        if (fileSection == 4):
            timeStamp =  csvData[0][0]
            main.myStream.addAnnotation("TEST\\nENDED", adjustTime(timeStamp))
            main.myStream.addDataPoint('I/O-1', 'SpeedIO', "endSeq", adjustTime(timeStamp)+0.01)
            main.myStream.addDataPoint('Data-1', 'Data', "endSeq", adjustTime(timeStamp)+0.01)

            
            #print ("TEST ENDED AT " + timeStamp)
            resultsFile.close ()               
            
            return skipFileLines

        

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










