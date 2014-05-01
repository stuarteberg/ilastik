
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# Copyright 2011-2014, the ilastik developers

from opDataSelection import OpDataSelection, DatasetInfo
from lazyflow.operators.ioOperators import OpStackToH5Writer, OpH5WriterBigDataset

import os
import vigra
from lazyflow.utility import PathComponents
from lazyflow.utility.timer import timeLogged
from ilastik.utility import bind
from lazyflow.utility.pathHelpers import getPathVariants, isUrl
import ilastik.utility.globals

from ilastik.applets.base.appletSerializer import \
    AppletSerializer, getOrCreateGroup, deleteIfPresent

import logging
logger = logging.getLogger(__name__)

class DataSelectionSerializer( AppletSerializer ):
    """
    Serializes the user's input data selections to an ilastik v0.6 project file.
    
    The model operator for this serializer is the ``OpMultiLaneDataSelectionGroup``
    """
    # Constants    
    LocationStrings = { DatasetInfo.Location.FileSystem      : 'FileSystem',
                        DatasetInfo.Location.ProjectInternal : 'ProjectInternal' }

    def __init__(self, topLevelOperator, projectFileGroupName):
        super( DataSelectionSerializer, self ).__init__(projectFileGroupName)
        self.topLevelOperator = topLevelOperator
        self._dirty = False
        self.caresOfHeadless = True
        
        self._projectFilePath = None
        
        self.version = '0.2'
        
        def handleDirty():
            if not self.ignoreDirty:
                self._dirty = True

        self.topLevelOperator.ProjectFile.notifyDirty( bind(handleDirty) )
        self.topLevelOperator.ProjectDataGroup.notifyDirty( bind(handleDirty) )
        self.topLevelOperator.WorkingDirectory.notifyDirty( bind(handleDirty) )
        
        def handleNewDataset(slot, roleIndex):
            slot[roleIndex].notifyDirty( bind(handleDirty) )
            slot[roleIndex].notifyDisconnect( bind(handleDirty) )
        def handleNewLane(multislot, laneIndex):
            assert multislot == self.topLevelOperator.DatasetGroup
            multislot[laneIndex].notifyInserted( bind(handleNewDataset) )
            for roleIndex in range( len(multislot[laneIndex]) ):
                handleNewDataset(multislot[laneIndex], roleIndex)
        self.topLevelOperator.DatasetGroup.notifyInserted( bind(handleNewLane) )

        # If a dataset was removed, we need to be reserialized.
        self.topLevelOperator.DatasetGroup.notifyRemoved( bind(handleDirty) )
        
    @timeLogged(logger, logging.DEBUG)
    def _serializeToHdf5(self, topGroup, hdf5File, projectFilePath):
        # Write any missing local datasets to the local_data group
        localDataGroup = getOrCreateGroup(topGroup, 'local_data')
        wroteInternalData = False
        for laneIndex, multislot in enumerate(self.topLevelOperator.DatasetGroup):
            for roleIndex, slot in enumerate( multislot ):
                if not slot.ready():
                    continue
                info = slot.value
                # If this dataset should be stored in the project, but it isn't there yet
                if  info.location == DatasetInfo.Location.ProjectInternal \
                and info.datasetId not in localDataGroup.keys():
                    # Obtain the data from the corresponding output and store it to the project.
                    dataSlot = self.topLevelOperator._NonTransposedImageGroup[laneIndex][roleIndex]

                    try:    
                        opWriter = OpH5WriterBigDataset(parent=self.topLevelOperator.parent, graph=self.topLevelOperator.graph)
                        opWriter.CompressionEnabled.setValue(False) # Compression slows down browsing a lot, and raw data tends to be noisy and doesn't compress very well, anyway.
                        opWriter.hdf5File.setValue( localDataGroup )
                        opWriter.hdf5Path.setValue( info.datasetId )
                        opWriter.Image.connect(dataSlot)
        
                        # Trigger the copy
                        success = opWriter.WriteImage.value
                        assert success
                    finally:
                        opWriter.cleanUp()
    
                    # Add axistags and drange attributes, in case someone uses this dataset outside ilastik
                    localDataGroup[info.datasetId].attrs['axistags'] = dataSlot.meta.axistags.toJSON()
                    if dataSlot.meta.drange is not None:
                        localDataGroup[info.datasetId].attrs['drange'] = dataSlot.meta.drange
    
                    # Make sure the dataSlot's axistags are updated with the dataset as we just wrote it
                    # (The top-level operator may use an OpReorderAxes, which changed the axisorder)
                    info.axistags = dataSlot.meta.axistags
    
                    wroteInternalData = True

        # Construct a list of all the local dataset ids we want to keep
        localDatasetIds = set()
        for laneIndex, multislot in enumerate(self.topLevelOperator.DatasetGroup):
            for roleIndex, slot in enumerate(multislot):
                if slot.ready() and slot.value.location == DatasetInfo.Location.ProjectInternal:
                    localDatasetIds.add( slot.value.datasetId )
        
        # Delete any datasets in the project that aren't needed any more
        for datasetName in localDataGroup.keys():
            if datasetName not in localDatasetIds:
                del localDataGroup[datasetName]

        if wroteInternalData:
            # We can only re-configure the operator if we're not saving a snapshot
            # We know we're saving a snapshot if the project file isn't the one we deserialized with.
            if self._projectFilePath is None or self._projectFilePath == projectFilePath:
                # Force the operator to setupOutputs() again so it gets data from the project, not external files
                firstInfo = self.topLevelOperator.DatasetGroup[0][0].value
                self.topLevelOperator.DatasetGroup[0][0].setValue(firstInfo, check_changed=False)

        deleteIfPresent(topGroup, 'Role Names')
        topGroup.create_dataset('Role Names', data=self.topLevelOperator.DatasetRoles.value)

        # Access the info group
        infoDir = getOrCreateGroup(topGroup, 'infos')
        
        # Delete all infos
        for infoName in infoDir.keys():
            del infoDir[infoName]
                
        # Rebuild the list of infos
        roleNames = self.topLevelOperator.DatasetRoles.value
        for laneIndex, multislot in enumerate(self.topLevelOperator.DatasetGroup):
            laneGroupName = 'lane{:04d}'.format(laneIndex)
            laneGroup = infoDir.create_group( laneGroupName )
            
            for roleIndex, slot in enumerate(multislot):
                infoGroup = laneGroup.create_group( roleNames[roleIndex] )
                if slot.ready():
                    datasetInfo = slot.value
                    locationString = self.LocationStrings[datasetInfo.location]
                    infoGroup.create_dataset('location', data=locationString)
                    infoGroup.create_dataset('filePath', data=datasetInfo.filePath)
                    infoGroup.create_dataset('datasetId', data=datasetInfo.datasetId)
                    infoGroup.create_dataset('allowLabels', data=datasetInfo.allowLabels)
                    infoGroup.create_dataset('nickname', data=datasetInfo.nickname)
                    if datasetInfo.drange is not None:
                        infoGroup.create_dataset('drange', data=datasetInfo.drange)
                    if datasetInfo.axistags is not None:
                        infoGroup.create_dataset('axistags', data=datasetInfo.axistags.toJSON())
                        axisorder = "".join(tag.key for tag in datasetInfo.axistags)
                        infoGroup.create_dataset('axisorder', data=axisorder)
                    if datasetInfo.subvolume_roi is not None:
                        infoGroup.create_dataset('subvolume_roi', data=datasetInfo.subvolume_roi)
                        

        self._dirty = False

    def importStackAsLocalDataset(self, info):
        """
        Add the given stack data to the project file as a local dataset.
        Does not update the topLevelOperator.
        
        :param info: A DatasetInfo object.
                     Note: info.filePath must be a stack files must be separated by '//' tokens.
                     Note: info will be MODIFIED by this function.  Use the modified info when assigning it to a dataset.
        """
        try:
            self.progressSignal.emit(0)
            
            projectFileHdf5 = self.topLevelOperator.ProjectFile.value
            topGroup = getOrCreateGroup(projectFileHdf5, self.topGroupName)
            localDataGroup = getOrCreateGroup(topGroup, 'local_data')

            globstring = info.filePath
            info.location = DatasetInfo.Location.ProjectInternal
            firstPathParts = PathComponents(info.filePath.split('//')[0])
            info.filePath = firstPathParts.externalDirectory + '/??' + firstPathParts.extension

            # Use absolute path
            cwd = self.topLevelOperator.WorkingDirectory
            if '//' not in globstring and not os.path.isabs(globstring):
                globstring = os.path.normpath( os.path.join(cwd, globstring) )
            
            opWriter = OpStackToH5Writer(parent=self.topLevelOperator.parent, graph=self.topLevelOperator.graph)
            opWriter.hdf5Group.setValue(localDataGroup)
            opWriter.hdf5Path.setValue(info.datasetId)
            opWriter.GlobString.setValue(globstring)
                
            # Forward progress from the writer directly to our applet                
            opWriter.progressSignal.subscribe( self.progressSignal.emit )
            
            success = opWriter.WriteImage.value
            
        finally:
            opWriter.cleanUp()
            self.progressSignal.emit(100)

        return success

    def initWithoutTopGroup(self, hdf5File, projectFilePath):
        """
        Overridden from AppletSerializer.initWithoutTopGroup
        """
        # The 'working directory' for the purpose of constructing absolute 
        #  paths from relative paths is the project file's directory.
        projectDir = os.path.split(projectFilePath)[0]
        self.topLevelOperator.WorkingDirectory.setValue( projectDir )
        self.topLevelOperator.ProjectDataGroup.setValue( self.topGroupName + '/local_data' )
        self.topLevelOperator.ProjectFile.setValue( hdf5File )
        
        self._dirty = False

    @timeLogged(logger, logging.DEBUG)
    def _deserializeFromHdf5(self, topGroup, groupVersion, hdf5File, projectFilePath, headless):
        self._projectFilePath = projectFilePath
        self.initWithoutTopGroup(hdf5File, projectFilePath)
        
        # normally the serializer is not dirty after loading a project file
        # however, when the file was corrupted, the user has the possibility
        # to save the fixed file after loading it.
        infoDir = topGroup['infos']
        localDataGroup = topGroup['local_data']
        
        assert self.topLevelOperator.DatasetRoles.ready(), \
            "Expected dataset roles to be hard-coded by the workflow."
        workflow_role_names = self.topLevelOperator.DatasetRoles.value

        # If the project file doesn't provide any role names, then we assume this is an old pixel classification project
        force_dirty = False
        backwards_compatibility_mode = ('Role Names' not in topGroup)
        self.topLevelOperator.DatasetGroup.resize( len(infoDir) )

        # The role names MAY be different than those that we have loaded in the workflow 
        #   because we might be importing from a project file made with a different workflow.
        # Therefore, we don't assert here.
        # assert workflow_role_names == list(topGroup['Role Names'][...])
        
        # Use the WorkingDirectory slot as a 'transaction' guard.
        # To prevent setupOutputs() from being called a LOT of times during this loop,
        # We'll disconnect it so the operator is not 'configured' while we do this work.
        # We'll reconnect it after we're done so the configure step happens all at once.
        working_dir = self.topLevelOperator.WorkingDirectory.value
        self.topLevelOperator.WorkingDirectory.disconnect()
        
        for laneIndex, (_, laneGroup) in enumerate( sorted(infoDir.items()) ):
            
            # BACKWARDS COMPATIBILITY:
            # Handle projects that didn't support multiple datasets per lane
            if backwards_compatibility_mode:
                assert 'location' in laneGroup
                datasetInfo, dirty = self._readDatasetInfo(laneGroup, localDataGroup, projectFilePath, headless)
                force_dirty |= dirty

                # Give the new info to the operator
                self.topLevelOperator.DatasetGroup[laneIndex][0].setValue(datasetInfo)
            else:
                for roleName, infoGroup in sorted(laneGroup.items()):
                    roleIndex = workflow_role_names.index( roleName )
                    datasetInfo, dirty = self._readDatasetInfo(infoGroup, localDataGroup, projectFilePath, headless)
                    force_dirty |= dirty
    
                    # Give the new info to the operator
                    if datasetInfo is not None:
                        self.topLevelOperator.DatasetGroup[laneIndex][roleIndex].setValue(datasetInfo)

        # Finish the 'transaction' as described above.
        self.topLevelOperator.WorkingDirectory.setValue( working_dir )
        
        self._dirty = force_dirty
    
    def _readDatasetInfo(self, infoGroup, localDataGroup, projectFilePath, headless):
        # Unready datasets are represented with an empty group.
        if len( infoGroup ) == 0:
            return None, False
        datasetInfo = DatasetInfo()

        # Make a reverse-lookup of the location storage strings
        LocationLookup = { v:k for k,v in self.LocationStrings.items() }
        datasetInfo.location = LocationLookup[ str(infoGroup['location'].value) ]
        
        # Write to the 'private' members to avoid resetting the dataset id
        datasetInfo._filePath = infoGroup['filePath'].value
        datasetInfo._datasetId = infoGroup['datasetId'].value

        try:
            datasetInfo.allowLabels = infoGroup['allowLabels'].value
        except KeyError:
            pass
        
        try:
            datasetInfo.drange = tuple( infoGroup['drange'].value )
        except KeyError:
            pass
        
        try:
            datasetInfo.nickname = infoGroup['nickname'].value
        except KeyError:
            datasetInfo.nickname = PathComponents(datasetInfo.filePath).filenameBase
        
        try:
            tags = vigra.AxisTags.fromJSON( infoGroup['axistags'].value )
            datasetInfo.axistags = tags
        except KeyError:
            # Old projects just have an 'axisorder' field instead of full axistags
            try:
                axisorder = infoGroup['axisorder'].value
                datasetInfo.axistags = vigra.defaultAxistags(axisorder)
            except KeyError:
                pass
        
        try:
            start, stop = map( tuple, infoGroup['subvolume_roi'].value )
            datasetInfo.subvolume_roi = (start, stop)
        except KeyError:
            pass
        
        # If the data is supposed to be in the project,
        #  check for it now.
        if datasetInfo.location == DatasetInfo.Location.ProjectInternal:
            if not datasetInfo.datasetId in localDataGroup.keys():
                raise RuntimeError("Corrupt project file.  Could not find data for " + infoGroup.name)

        dirty = False
        # If the data is supposed to exist outside the project, make sure it really does.
        if datasetInfo.location == DatasetInfo.Location.FileSystem and not isUrl(datasetInfo.filePath):
            pathData = PathComponents( datasetInfo.filePath, os.path.split(projectFilePath)[0])
            filePath = pathData.externalPath
            if not os.path.exists(filePath):
                if headless:
                    raise RuntimeError("Could not find data at " + filePath)
                filt = "Image files (" + ' '.join('*.' + x for x in OpDataSelection.SupportedExtensions) + ')'
                newpath = self.repairFile(filePath, filt)
                if pathData.internalPath is not None:
                    newpath += pathData.internalPath
                datasetInfo._filePath = getPathVariants(newpath , os.path.split(projectFilePath)[0])[0]
                dirty = True
        
        return datasetInfo, dirty
                
    
    def updateWorkingDirectory(self,newpath,oldpath):
        newdir = PathComponents(newpath).externalDirectory
        olddir = PathComponents(oldpath).externalDirectory
        
        if newdir==olddir:
            return
 
        # Disconnect the working directory while we make these changes.
        # All the changes will take effect when we set the new working directory.
        self.topLevelOperator.WorkingDirectory.disconnect()
        
        for laneIndex, multislot in enumerate(self.topLevelOperator.DatasetGroup):
            for roleIndex, slot in enumerate(multislot):
                if not slot.ready():
                    # Skip if there is no dataset in this lane/role combination yet.
                    continue
                datasetInfo = slot.value
                if datasetInfo.location == DatasetInfo.Location.FileSystem:
                    
                    #construct absolute path and recreate relative to the new path
                    fp = PathComponents(datasetInfo.filePath,olddir).totalPath()
                    abspath, relpath = getPathVariants(fp,newdir)
                    
                    # Same convention as in dataSelectionGui:
                    # Relative by default, unless the file is in a totally different tree from the working directory.
                    if relpath is not None and len(os.path.commonprefix([fp, abspath])) > 1:
                        datasetInfo.filePath = relpath
                    else:
                        datasetInfo.filePath = abspath
                    
                    slot.setValue(datasetInfo, check_changed=False)
        
        self.topLevelOperator.WorkingDirectory.setValue(newdir)
        self._projectFilePath = newdir
        
    def isDirty(self):
        """ Return true if the current state of this item 
            (in memory) does not match the state of the HDF5 group on disk.
            SerializableItems are responsible for tracking their own dirty/notdirty state."""
        return self._dirty

    def unload(self):
        """ Called if either
            (1) the user closed the project or
            (2) the project opening process needs to be aborted for some reason
                (e.g. not all items could be deserialized properly due to a corrupted ilp)
            This way we can avoid invalid state due to a partially loaded project. """ 
        self.topLevelOperator.DatasetGroup.resize( 0 )


class Ilastik05DataSelectionDeserializer(AppletSerializer):
    """
    Deserializes the user's input data selections from an ilastik v0.5 project file.
    """
    def __init__(self, topLevelOperator):
        super( Ilastik05DataSelectionDeserializer, self ).__init__( '' )
        self.topLevelOperator = topLevelOperator
    
    def serializeToHdf5(self, hdf5File, projectFilePath):
        # This class is for DEserialization only.
        pass

    def deserializeFromHdf5(self, hdf5File, projectFilePath, headless = False):
        # Check the overall file version
        ilastikVersion = hdf5File["ilastikVersion"].value

        # This is the v0.5 import deserializer.  Don't work with 0.6 projects (or anything else).
        if ilastikVersion != 0.5:
            return

        # The 'working directory' for the purpose of constructing absolute 
        #  paths from relative paths is the project file's directory.
        projectDir = os.path.split(projectFilePath)[0]
        self.topLevelOperator.WorkingDirectory.setValue( projectDir )

        # Access the top group and the info group
        try:
            #dataset = hdf5File["DataSets"]["dataItem00"]["data"]
            dataDir = hdf5File["DataSets"]
        except KeyError:
            # If our group (or subgroup) doesn't exist, then make sure the operator is empty
            self.topLevelOperator.DatasetGroup.resize( 0 )
            return
        
        self.topLevelOperator.DatasetGroup.resize( len(dataDir) )
        for index, (datasetDirName, datasetDir) in enumerate( sorted(dataDir.items()) ):
            datasetInfo = DatasetInfo()

            # We'll set up the link to the dataset in the old project file, 
            #  but we'll set the location to ProjectInternal so that it will 
            #  be copied to the new file when the project is saved.    
            datasetInfo.location = DatasetInfo.Location.ProjectInternal
            
            # Some older versions of ilastik 0.5 stored the data in tzyxc order.
            # Some power-users can enable a command-line flag that tells us to 
            #  transpose the data back to txyzc order when we import the old project.
            default_axis_order = ilastik.utility.globals.ImportOptions.default_axis_order
            if default_axis_order is not None:
                import warnings
                warnings.warn( "Using a strange axis order to import ilastik 0.5 projects: {}".format( default_axis_order ) )
                datasetInfo.axistags = vigra.defaultAxistags(default_axis_order)
            
            # Write to the 'private' members to avoid resetting the dataset id
            totalDatasetPath = str(projectFilePath + '/DataSets/' + datasetDirName + '/data' )
            datasetInfo._filePath = totalDatasetPath
            datasetInfo._datasetId = datasetDirName # Use the old dataset name as the new dataset id
            datasetInfo.nickname = "{} (imported from v0.5)".format( datasetDirName )
            
            # Give the new info to the operator
            self.topLevelOperator.DatasetGroup[index][0].setValue(datasetInfo)

    def _serializeToHdf5(self, topGroup, hdf5File, projectFilePath):
        assert False

    def _deserializeFromHdf5(self, topGroup, groupVersion, hdf5File, projectFilePath):
        # This deserializer is a special-case.
        # It doesn't make use of the serializer base class, which makes assumptions about the file structure.
        # Instead, if overrides the public serialize/deserialize functions directly
        assert False


    def isDirty(self):
        """ Return true if the current state of this item 
            (in memory) does not match the state of the HDF5 group on disk.
            SerializableItems are responsible for tracking their own dirty/notdirty state."""
        return False

    def unload(self):
        """ Called if either
            (1) the user closed the project or
            (2) the project opening process needs to be aborted for some reason
                (e.g. not all items could be deserialized properly due to a corrupted ilp)
            This way we can avoid invalid state due to a partially loaded project. """ 
        self.topLevelOperator.DatasetGroup.resize( 0 )




















