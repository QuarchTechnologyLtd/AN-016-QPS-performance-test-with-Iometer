#!/usr/bin/env python
'''
This contains useful functions for Iometer automation with Quarch tools

########### VERSION HISTORY ###########

13/08/2018 - Andy Norrie    - First version, based on initial work from Pedro Leao
'''

'''
This function is normally called in a seperate thread and runs the Iometer process, using the given file name to
describe the tests to be carried out
'''

import time
import os
import subprocess
import threading
import multiprocessing as mp
from multiprocessing import Pipe
import csv
import datetime
import socket

try:
    # for Python 2.x
    from StringIO import StringIO
except ImportError:
    # for Python 3.x
    from io import StringIO

'''
Executes iometer within a seperate thread sub-process
'''
def runIOMeter(fileName):

    time.sleep(1)

    info = subprocess.STARTUPINFO()
    info.dwFlags = 1
    info.wShowWindow = 0

    runAsAdminCmd = "runas"
    
    proc = subprocess.Popen("IOmeter.exe /c "  + fileName + " /r testfile.csv", stdout = subprocess.PIPE, stderr = subprocess.PIPE, startupinfo=info)

    out, error = proc.communicate()

'''
Allows the given file to be iterated through, using a python 'generator' (allowing us to parse the IOmeter instant results file
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
Simple function to get time in the right format for QPS
TODO: Move this to a more central library and rename it to a more accurate name!
'''
def adjustTime(timestamp):
    return time.mktime(datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S:%f").timetuple())

'''
This function follows the data accumulating from Iometer, in the instant results file, and 
processes it into QPS, adding annotationsa and custom channel data points as needed.

This currently assumes that custom channels have been created for IOPS, Data and Response
'''
def processIometerInstResults(testName, skipFileLines, myStream, userCallbacks):    
        
    # Wait for the file to exist
    while(os.path.isfile("insttestfile.csv") == False): pass

    # Open the file for non-exclusive read
    resultsFile = open("insttestfile.csv", 'rb')
    # Attach the file iterator
    resultsIterator = followResultsFile (resultsFile)
    
    driveSpeed = ""
    fileSection = 0
    lineCount = 0
    lineCount2 = 0    
    sum_all_threads1 = 0
    sum_all_threads2 = 0
    sum_all_threads3 = 0
    testDescrip = "Undescribed Test"
    workerCount = 99999
    workerList = []
    resultsMap = {
        "IOPS": 0,
        "RATE": 0,
        "RESPONSE": 0,
    }
    
    for dataLine in resultsIterator:
        f = StringIO (dataLine.decode ('utf-8'))
        lineCount = lineCount + 1           

        if( lineCount < skipFileLines ):
            continue

        skipFileLines = skipFileLines + 1

        csvData = list(csv.reader (f))

        # Get the test description if there is one
        if (lineCount == 2):
           if (csvData[0][1] != ""):
               testDescrip = csvData[0][1]
        
        if (fileSection == 0 and csvData[0][0] != '\'Time Stamp'):            
            continue
        elif (fileSection == 0): 
            fileSection = 1
            continue

        if (fileSection == 1):            
            timeStamp =  csvData[0][0]
                     
            if (userCallbacks.has_key("TEST_START")):
                userCallbacks["TEST_START"](myStream, timeStamp, testDescrip)
            
            fileSection = 2
            continue        

        if (fileSection == 2 and csvData[0][0] != 'TimeStamp'):            
            continue
        elif (fileSection == 2): 
            fileSection = 3
            continue

        if (fileSection == 3):
            lineCount2 += 1
            prevTimeStamp = timeStamp
            timeStamp =  csvData[0][0]
            if (timeStamp == '\'Time Stamp'):
                fileSection = 4
                continue

            # Track the workers we have seen (add up until we see the same worker again)
            if (workerCount == 99999):
                if (workerList.__contains__ (csvData[0][2]) == False):
                    workerList.append (csvData[0][2])
                else:
                    # Store worker count
                    workerCount = len(workerList)

                    # Get Data in correct units for QPS
                    sum_all_threads2 = sum_all_threads2*1000000
                    sum_all_threads3 = sum_all_threads3 / workerCount

                    # Process the current result
                    resultsMap["IOPS"] = sum_all_threads1
                    resultsMap["DATA_RATE"] = sum_all_threads2
                    resultsMap["RESPONSE_TIME"] = sum_all_threads3
                    if (userCallbacks.has_key("TEST_RESULT")):
                        userCallbacks["TEST_RESULT"] (myStream, prevTimeStamp, resultsMap)                    
                
                    sum_all_threads1 = 0
                    sum_all_threads2 = 0
                    sum_all_threads3 = 0

            # Sum up the values from each worker
            dataValue1 = csvData[0][7]
            dataValue2 = csvData[0][13]
            dataValue3 = csvData[0][18]            
            sum_all_threads1 += float(dataValue1)
            sum_all_threads2 += float(dataValue2)
            sum_all_threads3 += float(dataValue3)
            
            if (lineCount2 % workerCount == 0):
                
                # Get Data in correct units for QPS
                sum_all_threads2 = sum_all_threads2*1000000
                sum_all_threads3 = sum_all_threads3 / workerCount

                resultsMap["IOPS"] = sum_all_threads1
                resultsMap["DATA_RATE"] = sum_all_threads2
                resultsMap["RESPONSE_TIME"] = sum_all_threads3
                if (userCallbacks.has_key("TEST_RESULT")):
                        userCallbacks["TEST_RESULT"] (myStream, prevTimeStamp, resultsMap)
                #myStream.addDataPoint('I/O', 'IOPS', sum_all_threads1, adjustTime(timeStamp))
                #myStream.addDataPoint('Data', 'Data', sum_all_threads2, adjustTime(timeStamp))
                #myStream.addDataPoint('Response', 'Response', sum_all_threads3, adjustTime(timeStamp))
                
                sum_all_threads1 = 0
                sum_all_threads2 = 0
                sum_all_threads3 = 0
                
            #print ('LOG ' + timeStamp + " " + dataValue)
            #myStream.addDataPoint('I/O-1', 'SpeedIO', dataValue1, adjustTime(timeStamp))
            #myStream.addDataPoint('Mb-1', 'SpeedMb', dataValue2, adjustTime(timeStamp))

        if (fileSection == 4):
            timeStamp =  csvData[0][0]
            if (userCallbacks.has_key("TEST_END")):
                userCallbacks["TEST_END"](myStream, timeStamp, testDescrip)
            
            #print ("TEST ENDED AT " + timeStamp)
            resultsFile.close ()               
            
            return skipFileLines
			
'''
Scans the given path for .conf files (ioMeter template files) and
creates .icf files with the correct host and drive target information in place
'''
def generateIcfFromConf(confPath, driveInfo, managerName=socket.gethostname()):

    configFiles = []
    fileCount = 0
    
    config_list = []
    
    # Scan through .conf files
    for file in os.listdir(confPath):
        if file.endswith(".conf"):
        
            confFilePath = os.path.join(confPath, file)
            icfFilePath = confFilePath.replace ('.conf', '.icf')

            # Delete any old icf file with the same name
            if os.path.exists(icfFilePath):
                os.remove(icfFilePath)        

            # Open the .conf file
            openFile = open (confFilePath)
            fileData = openFile.read ()
            openFile.close ()
   
            # Create the string modifications needed to set the correct target
            newStr = "\t" + str(driveInfo["PHYSICALDRIVE"]) +  ": \"" + str(driveInfo["NAME"]) + " " + str(driveInfo["FW_REV"]) + "\"" + "\n"
            oldStr = "[*TARGET*]"
            # Replace the string
            fileData = fileData.replace(str(oldStr),str(newStr))
			
			# Create the string modification to set the manager name
			newStr = "\t" + managerName + "\n"
            oldStr = "[*MANAGER*]"
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