#!/usr/bin/env python
## See Notes at bottom for setup.

import argparse
import bisect
import csv        
import glob
import json
import logging
import os.path
import pprint
import sys
#import pdb #pdb.set_trace()

SCRIPTNAME = os.path.basename(sys.argv[0])
LOGNAME = os.path.splitext(SCRIPTNAME)[0] + '.log'

# Logging levels (least to most verbose):
_LOGGING_LEVELS = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']

# Remove non-ascii \n and \r from a string.
# ord() appears to work even with double-type chars.
def removeNonAsciiCRLF(s):
    return "".join(i for i in s if ord(i)<128).replace('\n', '\\n').replace('\r', '\\r')            
#   return ''.join(i if ord(i) < 128 else '?' for i in s).replace('\n', ' ').replace('\r', ' ')
#   str.encode('ascii','ignore') failed on some strings.

# Check if non-ascii or contains \n and \r.
def isNonAsciiCRLF(s):
    # Appears to work even with double-type chars.
    #return any(128<=ord(i) for i in s) or '\n' in s or '\r' in s
    try:
        s.encode('ascii')
    except: # UnicodeEncodeError:
        return True
    else:
        if '\n' in s or '\r' in s:
            return True
        else:
            return False

# List method that mimics string.find() behavior
def listFind(aList,value):
    try:
        index = aList.index(value)
    except ValueError:
        index = -1
    return index

# List method that returns value at specified index or a default
def listGet(aList,indx,default):
    #value = default
    #if indx < len(aList):
    #    value = aList[indx]
    #return value
    try:
        value = aList[indx]
    except IndexError:
        value = default
    return value

# List method to remove trailing whitespace elements.
def listRStrip(aList):
    while len(aList) and not aList[-1].strip():
        aList.pop()

# Write to log when the rest of a row is ignored.
def logIfRemainder(aList,indx,msgPrefix):
    if indx < len(aList):
        logging.warning("{} Ignoring cells {}".format(msgPrefix,aList[indx:]))
def ignoredCellsWarning(logWhere,cells):
    if cells:
        logging.warning("{} Ignoring cells {}".format(logWhere,cells))
    
# Return starting index of "team","id",<categories> headings.
# Headings must be in the order "team", "id", <categories>.
# But check for categories after, since that is where error message will be sent.
def getHeadingIndex(row):
    teamIndex=listFind(row,"team")
    idIndex=listFind(row,"id")
    if 0 < teamIndex and teamIndex+1 == idIndex: # and idIndex+1 < len(row):
        return teamIndex
    else:
        return -1

def sheetDefined(sheet):
    if sheet['grade'] and sheet['gender'] and sheet['eType']:
        return True
    else:
        return False
    
# Process arguments
# Could use type=argparse.FileType('r'), but need to easily get list of filenames.
parser = argparse.ArgumentParser()
parser.add_argument('files',
                    nargs='+',
                    help='JSon or csv files containing evaluation data')
parser.add_argument('--log-level',
                    default='WARNING',
                    dest='log_level',
                    choices=_LOGGING_LEVELS,
                    nargs='?',
                    help='Set the logging output level')
#parser.add_argument("--pdb", default=False)
args = parser.parse_args()

# Configure logging
logging.basicConfig(filename=LOGNAME, filemode='w', level=args.log_level)
logging.info('Argument List: %s', str(sys.argv))

# Handle file wildcards
gfilelist = []
for argf in args.files:
    for globargf in glob.glob(argf):
        gfilelist.append(globargf)
        
# Remove duplicates and sort the list of files.
filelist = sorted(list(set(gfilelist)))
logging.info('Files (%s): %s', len(filelist), filelist)

# Define patterns for processing the player id (in csv and excel files).
leadingChars="^[a-z,A-Z]*"
endingNums="[0-9]*$"

# Read each file,
# determine the type and put non-JSON files into the JSON format of the app datafile.
#
# Then process all of the data into a single dictionary structure for printing.
#{
#  '6thGirlsNight1': {
#    'kComments': [
#      'File soccer.1.68.txt: Session 0522_6-8pm: Sheet 6thGirlsNight1Station5Group3: Has comment - Thanks so'
#    ],
#    'data': {
#      'White': {
#        '38': {
#          'Station5': {
#            'ratings': {'A':'', 'B':''},
#            'total': 0
#          },
#          'pComments': 'In station Station5 but with no ratings. '
#        },
#      },
#      'Green': {
#        '34': {
#          'Station5': {
#            'ratings': {'A':4, 'B':4},
#            'total': 8
#          }
#        },
#      }
#    },
#    'categories': ['A','B'],
#    'stationList': ['Station5']
#  }
#}
#
# When processed, team values ("Green", "White", "Red", or "Blue")
#   will be changed to "g", w", "r", "b".                                      

# Collect the data as a list of dictionaries,
# one dictionary for each valid file.
logging.info("=== Collecting data from files...")
allData = []

for filenum in range(len(filelist)):
    tabletFile = filelist[filenum]   
    tabletFileType = "undefined"
    filename=filelist[filenum]

    logWhere="File {}".format(filename)
    logging.info("{}: Processing...".format(logWhere))
    
    file_data = {}
    # Try to load as a JSON file.  Assume it is already in desired format.
    try:
        logging.debug("{}: Trying to load as json file...".format(logWhere))
        with open(tabletFile,'r') as tablet_file:
        # json.load returns a dictionary                                                                     
            file_data = json.load(tablet_file)
            tabletFileType = "json"
    except:
        logging.debug("{}: Error {}".format(logWhere,sys.exc_info()[:2]))
        pass

    if tabletFileType == "undefined":
        # Try to load as a csv file.  Best to do last since open() will open other types.
        #
        # Assume:
        #   "," is the delimiter
        #   For format, see example *.csv
        #
        
        # Sheet keys
        sheetKeysStr=["eType","grade","gender","field","group","comments","ratingTip"]
        sheetKeysList=["teams","categories","ratingValues"]
        
        # Set initial values
        validCsvData=True
        sessionSelected={}
        sheetSelected={}
        playerDataColumn=-1
        playerTeam="UNSET"
        
        try:
            logging.debug("{}: Trying to load as csv file...".format(logWhere))
            file_data = {"version": "", "sessions": []}
            with open(tabletFile,'r') as tablet_file:
                reader = csv.reader(tablet_file)

                for rowIndex, row in enumerate(reader):
                    logWhere="File {}: Row {}".format(filename,rowIndex+1)
                    #logging.debug("{}: row={}".format(logWhere,row))

                    # Don't try to handle non-ascii data.
                    # App should prevent it but currently allows non-ascii in comments and ratingTip.
                    if any(isNonAsciiCRLF(item) for item in row):
                        logging.error("{}: Data files cannot contain non-ascii data".format(logWhere))
                        validCsvData=False
                        break
                    
                    # Strip each item in the row,
                    # String trailing cells that have only whitespace
                    # Skip empty rows
                    row=[item.strip() for item in row]
                    listRStrip(row)
                    if not row:
                        continue

                    # Find first non-empty cellIndex, cellValue.
                    # One always exists due to skipping of empty rows above.
                    cellIndex = next((indx for indx, val in enumerate(row) if val))
                    cellValue = row[cellIndex]

                    # Skip lastRatingsChange
                    if cellValue == "lastRatingsChange":
                        continue
                    
                    # Used to determine if this row has player data column headings.
                    rowHeadingIndex=getHeadingIndex(row)

                    # Player data column headings in a role override any leading keywords (e.g., sessionName),
                    # so we check for that first.
                    if 0 < rowHeadingIndex:  # Row contains column headings for player data section
                        if sheetSelected and sheetDefined(sheetSelected) and playerDataColumn < 0:  # Entering player data section
                            # Record index of "team" heading.
                            playerDataColumn=rowHeadingIndex
                            
                            # Check and set categories; remove last item if "lastRatingsChange"
                            categories=row[playerDataColumn+2:]
                            if categories[-1] == "lastRatingsChange":
                                categories = categories[:-1]

                            if not categories:
                                logging.error("{}: Player data column headings are missing categories".format(logWhere))
                                validCsvData=False
                                break
     
                            if sheetSelected["categories"]:
                                if sheetSelected["categories"] != categories:
                                    logging.error("{}: Categories definitions do not match".format(logWhere))
                                    logging.error(categories[-1])
                                    validCsvData=False
                                    break
                            else:
                                sheetSelected["categories"] = categories
                            
                            logging.debug("{}: Set playerData start index".format(logWhere))
                            # TODO: Warn if ignoring cells before playerDataColumn aList[start:end]
                            #ignoredCellsWarning(logWhere,row[:playerDataColumn])

                        elif not sheetSelected or not sheetDefined(sheetSelected):
                            logging.error("{}: SheetName must be defined (sheetname, eType, grade, gender) before player data section".format(logWhere))
                            validCsvData=False
                            break
                            
                        else: # 0 <= playerDataColumn ; already in player data section
                            # Already in player data section
                            logging.warning("{}: Ignoring player data heading inside player data section".format(logWhere))

                    # Next we look for keywords
                    elif cellValue == "version":
                        if file_data["version"]:
                            logging.warning("{}: Warning: version already set".format(logWhere))
                        else:
                            # Record app version.
                            # Ignore remainder of row.
                            file_data["version"]=listGet(row,cellIndex+1,0)
                            logIfRemainder(row,cellIndex+2,"{}:".format(logWhere))

                    elif cellValue == "sessionName":  # Entering defining-session section
                        
                        # Save current data and start a new session.
                        if sheetSelected:
                            sessionSelected["sheets"].append(sheetSelected);
                            logging.debug("{}: Appended sheet {} to session {}".format(
                                logWhere,sheetSelected["sheetName"],sessionSelected["sessionName"]))
                            
                        if sessionSelected:
                            file_data["sessions"].append(sessionSelected);
                            logging.debug("{}: Appended session {} to file_data".format(
                                logWhere,sessionSelected["sessionName"]))
                        sessionSelected={"sessionName":"" ,"sheets":[]}
                        sheetSelected={}
                        
                        playerDataColumn=-1
                        playerTeam="UNSET"
                
                        # Record session name.
                        # Ignore remainder of row.
                        sessionSelected["sessionName"]=listGet(row,cellIndex+1,"UNSET")
                        logIfRemainder(row,cellIndex+2,"{}:".format(logWhere))

                    elif cellValue == "sheetName": # Entering defining-sheet section
                        # Create new session, if necessary.
                        if not sessionSelected["sessionName"]:
                            sessionSelected={"sessionName":"Default" ,"sheets":[]}
                            logging.info("{}: Sheet not in a session; defined default session".format(logWhere))
                    
                        # Save current data and start a new sheet.
                        if sheetSelected:
                            sessionSelected["sheets"].append(sheetSelected);
                            logging.debug("{}: Appended sheet {} to session {}".format(
                                logWhere,sheetSelected["sheetName"],sessionSelected["sessionName"]))
                        #sheetInit(sheetSelected)
                        sheetSelected={"sheetName":"","eType":"","teams":[],"grade":"","gender":"",
                           "field":"","group":"","comments":"","playerData":[],"categories":[],
                           "ratingValues":[],"ratingTip":""}
                        
                        playerDataColumn=-1
                        playerTeam="UNSET"

                        # Record sheet name.
                        # Ignore remainder of row.
                        sheetSelected["sheetName"]=listGet(row,cellIndex+1,"UNSET")
                        logIfRemainder(row,cellIndex+2,"{}:".format(logWhere))

                    elif cellValue in sheetKeysStr + sheetKeysList:
                        if sheetSelected and playerDataColumn < 0: # In defining-sheet section
                            if cellValue in sheetKeysStr:
                                # Record property.
                                # Ignore remainder of row.
                                sheetSelected[cellValue]=listGet(row,cellIndex+1,"")
                                logIfRemainder(row,cellIndex+2,"{}:".format(logWhere))
                                logging.debug("{}: Recorded {} in sheet {}".format(logWhere,cellValue,sheetSelected["sheetName"]))
                            
                            else: # cellValue in sheetKeysList:                            
                                # Record property.
                                # Ignore remainder of row.
                                sheetSelected[cellValue]=listGet(row,cellIndex+1,"").split(',')
                                logIfRemainder(row,cellIndex+2,"{}:".format(logWhere))
                                logging.debug("{}: Recorded {} in sheet {}".format(logWhere,cellValue,sheetSelected["sheetName"]))

                        elif not sheetSelected: 
                            logging.error("{}: SheetName must be set before sheet keys".format(logWhere))
                            validCsvData=False
                            break

                        else: # 0 <= playerDataColumn                           
                            logging.error("{}: When starting a new sheet, sheetName must be set before sheet keys".format(logWhere))
                            validCsvData=False
                            break

                    # Finally, we look for player data
                    elif 0 <= playerDataColumn: # In player data section
                        # Get team and id values
                        teamVal=""
                        idVal=""
                        if -1 < playerDataColumn < len(row):
                            teamVal=row[playerDataColumn]
                        if -1 < playerDataColumn+1 < len(row):
                            idVal=row[playerDataColumn+1]
                           
                        # If value in team column, set team.
                        # Team initally ="UNSET" and can be inherited from previous row, but Id cannot.
                        if teamVal or idVal:
                            if teamVal:
                                playerTeam=teamVal
                            else:
                                logging.info("{}: No team so using previous value".format(logWhere))
                                
                            if idVal:
                                # isinstance( playerId, ( int, long ) )
                                # try:
                                #     value = int(value)
                                # except ValueError:
                                #     pass  # it was a string, not an int.
                                playerId=idVal
                                
                                # Record ratings if non-empty TODO: should it record if empty?  What does app do?
                                ratings={}
                                for catIndex, cat in enumerate(sheetSelected["categories"]):
                                    ratingIndex=playerDataColumn+2+catIndex
                                    if ratingIndex < len(row) and row[ratingIndex]:
                                        ratings[cat]=row[ratingIndex]
                                sheetSelected["playerData"].append({"team":playerTeam,"id":playerId,"ratings":ratings})
                                logging.debug("{}: Appended player data to sheet {}".format(logWhere,sheetSelected["sheetName"]))
                            else:
                                logging.info("{}: No id so only recording team".format(logWhere))
                                
                        else:
                            logging.debug("{}: Neither team nor id values found in {}".format(logWhere,row))

                    else:
                        logging.warning("{}: No useful data found in {}".format(logWhere,row))
            
                # End of iteration over row
                            
                # TODO: Update format of backup csv created by tablet app; have it include version
                #       and update this script to look for it.

                if validCsvData:
                    tabletFileType = "csv"

                # Record last session and sheet worked on.
                if sheetSelected:
                    sessionSelected["sheets"].append(sheetSelected);
                    logging.debug("{}: Appended sheet {} to session {}".format(
                        logWhere,sheetSelected["sheetName"],sessionSelected["sessionName"]))
                if sessionSelected:
                    file_data["sessions"].append(sessionSelected);
                    logging.debug("{}: Appended session {} to file_data".format(
                        logWhere,sessionSelected["sessionName"]))

        except:
            logging.debug("{}: Error {}".format(logWhere,sys.exc_info()[:2]))
            pass
            
    if tabletFileType == "undefined":
        logComment="{}: Is not a valid json or csv file.".format(logWhere)
        logging.error(logComment)
        print "ERROR:",logComment
    else:
        file_data.update({'filename':tabletFile})
        allData.append(file_data)

# End of file processing

## Process all the data
logging.info("=== Processing all the data...")

# Define a python dictionary object, which indexes data for printing by keys.
compilation = {}
sshList = []

latestDBVersion = 0

for item in allData:
    filename=item['filename']
    basename, file_extension = os.path.splitext(filename)

    logWhere="File {}".format(filename)
    logging.info("{}: Processing...".format(logWhere))
    
    #print json.dumps(item, sort_keys=True)

    # TODO: Should we verify that expected keys exist?
    if 'version' in item and item['version']:
        try:
            dbVersion=int(item['version'])
        except:
            logging.error('{}: Skipping since db version {} is invalid.'.format(logWhere,item['version']))
            continue
        else:
            if dbVersion < latestDBVersion:
                 logging.warning('{}: Skipping since version {} is from an old db version.'.format(logWhere))
            elif 0 < latestDBVersion < dbVersion:
                logging.warning('{}: Has a more recent db version.  Discarding previous, older data.'.format(logWhere))
                compilation = {}
                sshList=[]
                latestDBVersion=dbVersion
    elif file_extension != ".csv":
        logging.error('{}: Skipping since db version is missing.'.format(logWhere))
        continue
    else:
        logging.warning('{}: Version key is missing, but processing anyway.'.format(logWhere))
    
    if 'sessions' not in item:
        logging.error('{}: Has no "sessions" key'.format(logWhere))
        continue
    for s in item['sessions']:
        sName=s['sessionName']
        
        logWhere="File {}: Session {}".format(filename,sName)
        logging.info("{}: Processing...".format(logWhere))

        if 'sheets' not in s:
            logging.error('{}: has no "sheets" key'.format(logWhere))
            continue
        for sh in s['sheets']:
            shName=sh['sheetName']

            logWhere="File {}: Session {}: Sheet {}".format(filename,sName,shName)
            logging.info("{}: Processing...".format(logWhere))

            # Check for duplicate session:sheet
            itemNew=(sName,shName,sh)
            if itemNew in sshList:
                logging.warning('{}: Skipping because it is a duplicate.'.format(logWhere))
                continue
            else:
                # Insert, in sort order, new sheet into sheet list.
                position=bisect.bisect(sshList,itemNew)
                bisect.insort(sshList,itemNew)

            # Proceed
            key=sh['grade']+sh['gender']+sh['eType']
            station=sh['field']
            group=sh['group']
            categories=sh['categories']
            ratingsValues=sh['ratingValues']

            # Check if sheet is empty
            if not sh['playerData']:
                logging.warning('{}: Skipping since it contains no players'.format(logWhere))
                continue
            
            # TODO - Update db in app and remove this kludge
            # Check for old ratingsValues (indicates old data)
            if file_extension != ".csv":
                isOld=0
                if (sh['eType']=='Night1' or sh['eType']=='Night2') and (len(sh['ratingValues']) != 6):
                    isOld=1
                elif (sh['eType']=='Bubble') and (len(sh['ratingValues']) != 20):
                    isOld=1
                if isOld:
                    # Should never get here unless db version incorrectly recorded in app
                    # or csv file is using wrong ratingValues.
                    # Any changes to pre-defined ratings should result in a new db version.
                    logging.warning('{}: Skipping since ratingsValues are old'.format(logWhere))
                    continue

            # Check for old session
            if sName[:4].isdigit():
                sNum=int(sName[1:4])
                if (sNum < 519):
                    logging.warning('{}: Possibly an old session; consider removing it,'.format(logWhere))
            
            # Record key
            if (key not in compilation):
                logging.debug('{}: Adding compilation[{}]'.format(logWhere,key))
                compilation[key]={'stationList':[],'categories':[],'kComments':[],'data':{}}

            # Check for sheetname having custom post-fix
            shPostFix=shName.replace(key+station+group,"",1)
            
            # Handle unset station/field
            if station=='':  # Should only happen with eType='Bubble' or 'Custom'
                station="Field"
                
            if shPostFix:
                # Record program comment.         
                logging.warning("{}: Adding custom post-fix {} to {}".format(logWhere,shPostFix,station))
                station+=shPostFix
                
            # If Bubble field, try to make it unique.
            if sh['eType']=='Bubble':
                if station in compilation.get(key,{}).get('stationList',[]):
                    # Rename station
                    nameFound=0
                    count=1
                    while (not nameFound) & (count < 10):
                        newStationName=station + '-' + str(count)
                        if (newStationName not in compilation[key]['stationList']):
                            nameFound=1
                            
                            # Record program comment.  Here since it's not necessary if new name comes from sheet name.
                            newProgComment="{}: Renamed {} to {}".format(logWhere,station,newStationName)
                            logging.info(newProgComment)
                            compilation[key]['kComments'].append("Program: "+newProgComment)
                            station=newStationName
                            
                            break
                        else:
                            count+=1
                    if not nameFound:
                        newProgComment="{}: Could not create unique name for duplicate station/field {}".format(logWhere,station)
                        logging.error(newProgComment)
                        compilation[key]['kComments'].append("Program: "+newProgComment)
                
            # Record sheet comment
            # First deal with non-ascii in comments.  Also remove \n and \r
            shComment_ascii=removeNonAsciiCRLF(sh['comments'])
            if shComment_ascii:
                newShComment="{}: Has comment - {}".format(logWhere,shComment_ascii)
                logging.info(newShComment)
                compilation[key]['kComments'].append(newShComment)
            
            # Record categories and make sure they match
            if (len(compilation[key]['categories'])) and (compilation[key]['categories'] != categories):
                # Should never get here unless db version incorrectly recorded in app.
                # Any changes to pre-defined categories or ratings should result in a new db version.
                logging.error('{}: Categories mismatch - {} != {}'.format(logWhere,compilation[key]['categories'],categories))
                continue
            else:
                logging.debug('{}: Recording categories {} in compilation'.format(logWhere,categories))
                compilation[key]['categories']=categories

            # First check if players in this sheet already appear in a sheet for the same station.
            # If so, rename the station.
            for p in sh['playerData']:                
                teamKey=p['team']
                idNum = p['id']
                if not type(idNum) is unicode:
                    # Why make it unicode?
                    idNum = unicode(idNum)
                if not str(idNum).isdigit():
                    continue
                if compilation[key]['data'].get(teamKey,{}).get(idNum,{}).has_key(station):
                    # Try to rename station
                    nameFound=0
                    count=1
                    while (not nameFound) & (count < 10):
                        newStationName=station + '-' + str(count)
                        if (newStationName not in compilation[key]['stationList']):
                            nameFound=1
                            # Record program comment
                            newProgComment="{}: Renamed {} to {}".format(logWhere,station,newStationName)
                            logging.info(newProgComment)
                            compilation[key]['kComments'].append("Program: "+newProgComment)
                            station=newStationName
                            break
                        else:
                            count+=1
            # End of check if players in this sheet already appear in a sheet for the same station.
            
            # Process each player in sheet
            for p in sh['playerData']:
                teamKey=p['team']
                idNum = p['id']

                # Why make it unicode?
                if not type(idNum) is unicode:
                    idNum = unicode(idNum)
                if not str(idNum).isdigit():
                    logging.error('File %s: Session %s: Sheet %s: Key %s: Team %s: Player %s is not a number.  Skipping',
                                  filename, sName, shName, key, teamKey, idNum)
                    continue

                logWhere="File {}: Session {}: Sheet {}: Player {}{}".format(filename,sName,shName,teamKey,idNum)
                logging.info("{}: Processing...".format(logWhere))
            
                # For recording player comments
                newPComment = ''
                
                # Record player team and id
                if (teamKey not in compilation[key]['data']):
                    logging.debug('{}: Recording team {} in compilation'.format(logWhere,teamKey))
                    compilation[key]['data'][teamKey]={}
                if (idNum not in compilation[key]['data'][teamKey]):
                    logging.debug('{}: Recording id {} in compilation'.format(logWhere,idNum))
                    compilation[key]['data'][teamKey].update({idNum:{}})

                # Record sources; NOT PRINTED YET
                #if 'sources' not in compilation[key]['data'][teamKey][idNum]:
                #    compilation[key]['data'][teamKey][idNum].update({'sources':[]})
                #logging.debug('{}: Recording source in compilation'.format(logWhere))
                #compilation[key]['data'][teamKey][idNum]['sources'].append("{}:{}:{}".format(filename, sName, shName))

                # Check for player appearing more than once in a station
                if (station in compilation[key]['data'][teamKey][idNum]):
                    logging.error('{}: Player already has scores for {}; recording in comments.'.format(logWhere,station))
                    # Add player comment
                    newPComment="File {} has additional scores for station {} ".format(filename,station)
                    for c in categories:
                        if c not in p['ratings']:
                            rating = ''
                        else:
                            rating = p['ratings'][c]
                        if rating == '':
                            rating = '\"\"'
                        newPComment+="{} = {} ".format(c,str(rating))
                    newPComment+='. '
                    
                    if 'pComments' not in compilation[key]['data'][teamKey][idNum]:
                        compilation[key]['data'][teamKey][idNum].update({'pComments':''})
        
                    logging.debug('{}: Adding comment {} to compilation'.format(logWhere,newPComment))          
                    compilation[key]['data'][teamKey][idNum]['pComments'] += newPComment
                    newPComment = ''
                    continue
                
                logging.info('{}: Adding {} ratings to compilation'.format(logWhere,station))
                compilation[key]['data'][teamKey][idNum].update({station:{'ratings':{},'total':''}})
                if (station not in compilation[key]['stationList']):
                    logging.debug('{}: Adding {} to stationlist'.format(logWhere,station))
                    compilation[key]['stationList'].append(station)

                # Get scores and total score for this player.
                total = 0
                ratingsCount = 0
                for c in categories:
                    # Validate rating and flag with a comment if necessary.
                    if c not in p['ratings']:
                        rating = ''
                    else:
                        rating = p['ratings'][c]
                        
                    if rating != '':
                        origRating = rating
                        if not (type(origRating) is float or str(origRating).isdigit()):
                            logging.error('{}: Invalid rating "{}"; an average will be used.'.format(logWhere,origRating))
                            newPComment += 'Invalid rating was ignored. '              
                        else:
                            # Make sure it's an int and warn if there is rounding.
                            # xlrd reads numbers as floats and json reads them as strings.
                            rating = int(round(float(origRating)))
                            ratingsCount += 1
                            total += rating
                            if (float(origRating) != rating):
                                logging.warning('{}: Rating "{}" was rounded to "{}"'.format(logWhere,origRating,rating))
                                newPComment += 'Decimal rating was rounded. '

                    logging.debug('{}: Adding rating {}={} to compilation'.format(logWhere,c, rating))
                    compilation[key]['data'][teamKey][idNum][station]['ratings'][c]=rating
                # End of ratings gathering

                # Record total for this player at this station.
                # Handle averaging of ratings (when ratings are missing)
                origTotal = total
                if 0 == ratingsCount:
                    logging.warning('{}: Has no ratings'.format(logWhere))
                    newPComment+="In station {} but with no ratings. ".format(station)
                    # TODO: If all ratings missing, should we ignore player for that station and give different error message?
                elif ratingsCount < len(categories):
                    logging.warning('{}: Missing ratings - an average will be used.'.format(logWhere))
                    newPComment += 'Missing rating so average used. '
                    total = int( round(len(categories) * total/float(ratingsCount)) )
                    
                logging.debug('{}: Adding total {} to compilation'.format(logWhere,total))
                compilation[key]['data'][teamKey][idNum][station]['total']=total
                
                # If there is a comment, record it.
                if newPComment:
                    logging.info('{}: Adding a comment to compilation'.format(logWhere))
                    if 'pComments' not in compilation[key]['data'][teamKey][idNum]:
                        compilation[key]['data'][teamKey][idNum].update({'pComments':''})
                    compilation[key]['data'][teamKey][idNum]['pComments'] += newPComment
                    logging.info('newPComment: %s', newPComment)
                    newPComment = ''

            # End of player processing
        # End of sheet processing
    # End of session processing
# End allData processing

# Print compilation
for key in sorted(compilation):
    print(key + ',')
    # First heading row
    print('id,'),
    for station in sorted(compilation[key]['stationList']):
        # Print for categories
        for c in compilation[key]['categories']:
            print(station + ','),
        # and for total
        if 1 < len(compilation[key]['categories']):
            print(station + ','),
    print('Comments (see ' + LOGNAME + ' for details),')

    # Second heading row
    print(','),
    for station in sorted(compilation[key]['stationList']):
        # Print heading for categories
        for c in compilation[key]['categories']:
            print(c + ','),
        # Print heading for total
        if 1 < len(compilation[key]['categories']):
            print('Total,'),
    print(',')

    for teamKey in sorted(compilation[key]['data']):
        for idNum in sorted(compilation[key]['data'][teamKey],key=int):
            # Use only 1 char of team and make lowercase
            print(str(teamKey.lower()[:1]) + str(idNum) + ','),

            for station in sorted(compilation[key]['stationList']):
                # Print station category scores
                for c in compilation[key]['categories']:
                    if station in compilation[key]['data'][teamKey][idNum]:
                        print(str(compilation[key]['data'][teamKey][idNum][station]['ratings'][c]) + ','),
                    else:
                        print(','),
                # Print station total
                if 1 < len(compilation[key]['categories']):
                    if station in compilation[key]['data'][teamKey][idNum]:
                        print(str(compilation[key]['data'][teamKey][idNum][station]['total']) + ','),
                    else:
                        print(','),
            # Print player comments
            if 'pComments' in compilation[key]['data'][teamKey][idNum]:
                print(str(compilation[key]['data'][teamKey][idNum]['pComments']) + ',')
            else:
                print(',')
            # End of station processing
        # End of idNum processing
    # End of teamKey processing
    # Print comments, if any
    if compilation[key]['kComments']:
        print('Comments:')
        for c in compilation[key]['kComments']:
            #print('  ' + c + ',')
            print('"  ' + c + '",')
    print(',')
# End of key processing 

## Notes
##
##  General
##    Python lists start at 0.
##
##  Setup
##    On Windows
##      Install python
##        Go to www.python.org/downloads/windows
##        and select, download and install the 2.7.11 MSI installer version.
##        Use the defaults when installing, but you may want to add the python.exe location to Path.
##        Verified installation by opening dos windows and entering "python -V".
##
##    On Mac
##      Python should already be installed
##

