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
def processIometerInstResults(testName, skipFileLines, myStream):
	
    driveSpeed = ""
    fileSection = 0
        
    # Wait for the file to exist
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
                     
            myStream.addAnnotation(testAnnotation + "\\n TEST STARTED", adjustTime(timeStamp))

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

                myStream.addDataPoint('I/O', 'IOPS', sum_all_threads1, adjustTime(timeStamp))
                myStream.addDataPoint('Data', 'Data', sum_all_threads2, adjustTime(timeStamp))
                
                sum_all_threads1 = 0
                sum_all_threads2 = 0
                
            #print ('LOG ' + timeStamp + " " + dataValue)
            #myStream.addDataPoint('I/O-1', 'SpeedIO', dataValue1, adjustTime(timeStamp))
            #myStream.addDataPoint('Mb-1', 'SpeedMb', dataValue2, adjustTime(timeStamp))

        if (fileSection == 4):
            timeStamp =  csvData[0][0]
            myStream.addAnnotation("TEST\\nENDED", adjustTime(timeStamp))
            myStream.addDataPoint('I/O', 'IOPS', "endSeq", adjustTime(timeStamp)+0.01)
            myStream.addDataPoint('Data', 'Data', "endSeq", adjustTime(timeStamp)+0.01)
            # TODO: Add the response channel
            # TODO: This should not be hardcoded here... we should be calling the  script level notifyXXXX functions by some means to the script can be easily tweaked (ask chris maybe?)
            
            #print ("TEST ENDED AT " + timeStamp)
            resultsFile.close ()               
            
            return skipFileLines