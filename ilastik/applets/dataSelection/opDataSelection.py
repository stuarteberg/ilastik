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

import uuid
import numpy
import vigra

from lazyflow.graph import Operator, InputSlot, OutputSlot, OperatorWrapper
from lazyflow.utility.jsonConfig import RoiTuple
from lazyflow.operators.ioOperators import OpStreamingHdf5Reader, OpInputDataReader
from lazyflow.operators.valueProviders import OpMetadataInjector
from ilastik.applets.base.applet import DatasetConstraintError

from ilastik.utility import OpMultiLaneWrapper
from lazyflow.operators.opReorderAxes import OpReorderAxes

class DatasetInfo(object):
    """
    Struct-like class for describing dataset info.
    """
    class Location():
        FileSystem = 0
        ProjectInternal = 1
        
    def __init__(self, jsonNamespace=None):
        Location = DatasetInfo.Location
        self.location = Location.FileSystem # Whether the data will be found/stored on the filesystem or in the project file
        self._filePath = ""                 # The original path to the data (also used as a fallback if the data isn't in the project yet)
        self._datasetId = ""                # The name of the data within the project file (if it is stored locally)
        self.allowLabels = True             # Whether or not this dataset should be used for training a classifier.
        self.drange = None
        self.normalizeDisplay = True
        self.fromstack = False
        self.nickname = ""
        self.axistags = None
        self.subvolume_roi = None

        if jsonNamespace is not None:
            self.updateFromJson( jsonNamespace )

    @property
    def filePath(self):
        return self._filePath
    
    @filePath.setter
    def filePath(self, newPath):
        self._filePath = newPath
        # Reset our id any time the filepath changes
        self._datasetId = str(uuid.uuid1())
    
    @property
    def datasetId(self):
        return self._datasetId
    
    DatasetInfoSchema = \
    {
        "_schema_name" : "dataset-info",
        "_schema_version" : 0.1,
        
        "filepath" : str,
        "drange" : tuple,
        "nickname" : str,
        "axistags" : str,
        "subvolume_roi" : RoiTuple()
    }

    def updateFromJson(self, namespace):
        """
        Given a namespace object returned by a JsonConfigParser,
        update the corresponding non-None fields of this DatasetInfo.
        """
        self.filePath = namespace.filepath or self.filePath        
        self.drange = namespace.drange or self.drange
        self.nickname = namespace.nickname or self.nickname
        if namespace.axistags is not None:
            self.axistags = vigra.defaultAxistags(namespace.axistags)

class OpDataSelection(Operator):
    """
    The top-level operator for the data selection applet, implemented as a single-image operator.
    The applet uses an OperatorWrapper to make it suitable for use in a workflow.
    """
    name = "OpDataSelection"
    category = "Top-level"
    
    SupportedExtensions = OpInputDataReader.SupportedExtensions

    # Inputs    
    ProjectFile = InputSlot(stype='object', optional=True) #: The project hdf5 File object (already opened)
    ProjectDataGroup = InputSlot(stype='string', optional=True) #: The internal path to the hdf5 group where project-local datasets are stored within the project file
    WorkingDirectory = InputSlot(stype='filestring') #: The filesystem directory where the project file is located
    Dataset = InputSlot(stype='object') #: A DatasetInfo object

    # Outputs
    Image = OutputSlot() #: The output image
    AllowLabels = OutputSlot(stype='bool') #: A bool indicating whether or not this image can be used for training

    _NonTransposedImage = OutputSlot() #: The output slot, in the data's original axis ordering (regardless of force5d)

    ImageName = OutputSlot(stype='string') #: The name of the output image
    
    class InvalidDimensionalityError(Exception):
        """Raised if the user tries to replace the dataset with a new one of differing dimensionality."""
        def __init__(self, message ):
            super( OpDataSelection.InvalidDimensionalityError, self ).__init__()
            self.message = message
        
        def __str__(self):
            return self.message

    def __init__(self, force5d=False, *args, **kwargs):
        super(OpDataSelection, self).__init__(*args, **kwargs)
        self.force5d = force5d
        self._previous_output_axiskeys = None
        self._opReaders = []

        # If the gui calls disconnect() on an input slot without replacing it with something else,
        #  we still need to clean up the internal operator that was providing our data.
        self.ProjectFile.notifyUnready(self.internalCleanup)
        self.ProjectDataGroup.notifyUnready(self.internalCleanup)
        self.WorkingDirectory.notifyUnready(self.internalCleanup)
        self.Dataset.notifyUnready(self.internalCleanup)

    def internalCleanup(self, *args):
        if len(self._opReaders) > 0:
            self.Image.disconnect()
            self._NonTransposedImage.disconnect()
            for reader in reversed(self._opReaders):
                reader.cleanUp()
            self._opReaders = []
    
    def setupOutputs(self):
        self.internalCleanup()
        datasetInfo = self.Dataset.value

        try:
            # Data only comes from the project file if the user said so AND it exists in the project
            datasetInProject = (datasetInfo.location == DatasetInfo.Location.ProjectInternal)
            datasetInProject &= self.ProjectFile.ready()
            if datasetInProject:
                internalPath = self.ProjectDataGroup.value + '/' + datasetInfo.datasetId
                datasetInProject &= internalPath in self.ProjectFile.value
    
            # If we should find the data in the project file, use a dataset reader
            if datasetInProject:
                opReader = OpStreamingHdf5Reader(parent=self)
                opReader.Hdf5File.setValue(self.ProjectFile.value)
                opReader.InternalPath.setValue(internalPath)
                providerSlot = opReader.OutputImage
                self._opReaders.append(opReader)
            else:
                # Use a normal (filesystem) reader
                opReader = OpInputDataReader(parent=self)
                if datasetInfo.subvolume_roi is not None:
                    opReader.SubVolumeRoi.setValue( datasetInfo.subvolume_roi )
                opReader.WorkingDirectory.setValue( self.WorkingDirectory.value )
                opReader.FilePath.setValue(datasetInfo.filePath)
                providerSlot = opReader.Output
                self._opReaders.append(opReader)
            
            # Inject metadata if the dataset info specified any.
            # Also, inject if if dtype is uint8, which we can reasonably assume has drange (0,255)
            if datasetInfo.normalizeDisplay is not None or \
               datasetInfo.drange is not None or \
               datasetInfo.axistags is not None or \
               (providerSlot.meta.drange is None and providerSlot.meta.dtype == numpy.uint8):
                metadata = {}
                if datasetInfo.drange is not None:
                    metadata['drange'] = datasetInfo.drange
                elif providerSlot.meta.dtype == numpy.uint8:
                    # SPECIAL case for uint8 data: Provide a default drange.
                    # The user can always override this herself if she wants.
                    metadata['drange'] = (0,255)
                if datasetInfo.normalizeDisplay is not None:
                    metadata['normalizeDisplay'] = datasetInfo.normalizeDisplay
                if datasetInfo.axistags is not None:
                    metadata['axistags'] = datasetInfo.axistags
                opMetadataInjector = OpMetadataInjector( parent=self )
                opMetadataInjector.Input.connect( providerSlot )
                opMetadataInjector.Metadata.setValue( metadata )
                providerSlot = opMetadataInjector.Output
                self._opReaders.append( opMetadataInjector )

            self._NonTransposedImage.connect(providerSlot)
            
            if self.force5d:
                op5 = OpReorderAxes(parent=self)
                op5.Input.connect(providerSlot)
                providerSlot = op5.Output
                self._opReaders.append(op5)
            
            # If the channel axis is not last (or is missing),
            #  make sure the axes are re-ordered so that channel is last.
            if providerSlot.meta.axistags.index('c') != len( providerSlot.meta.axistags )-1:
                op5 = OpReorderAxes( parent=self )
                keys = providerSlot.meta.getTaggedShape().keys()
                try:
                    # Remove if present.
                    keys.remove('c')
                except ValueError:
                    pass
                # Append
                keys.append('c')
                op5.AxisOrder.setValue( "".join( keys ) )
                op5.Input.connect( providerSlot )
                providerSlot = op5.Output
                self._opReaders.append( op5 )
            
            # Most workflows can't handle replacement of a dataset of a different dimensionality.
            # We guard against that by checking for errors NOW, before connecting our Image output,
            #  which is connected to the rest of the workflow.
            new_axiskeys = "".join( providerSlot.meta.getAxisKeys() )
            if self._previous_output_axiskeys is not None and len(new_axiskeys) != len(self._previous_output_axiskeys):
                msg =  "You can't replace an existing dataset with one of a different dimensionality.\n"\
                       "Your existing dataset was {}D ({}), but the new dataset is {}D ({}).\n"\
                       "Your original dataset entry has been reset.  "\
                       "Please remove it and then add your new dataset."\
                       "".format( len(self._previous_output_axiskeys), self._previous_output_axiskeys,
                                  len(new_axiskeys), new_axiskeys )
                raise OpDataSelection.InvalidDimensionalityError( msg )

            self._previous_output_axiskeys = new_axiskeys
            
            # Connect our external outputs to the internal operators we chose
            self.Image.connect(providerSlot)
            
            # Set the image name and usage flag
            self.AllowLabels.setValue( datasetInfo.allowLabels )
            
            imageName = datasetInfo.nickname
            if imageName == "":
                imageName = datasetInfo.filePath
            self.ImageName.setValue(imageName)
        
        except:
            self.internalCleanup()
            raise

    def propagateDirty(self, slot, subindex, roi):
        # Output slots are directly connected to internal operators
        pass

    @classmethod
    def getInternalDatasets(cls, filePath):
        return OpInputDataReader.getInternalDatasets( filePath )

class OpDataSelectionGroup( Operator ):
    # Inputs
    ProjectFile = InputSlot(stype='object', optional=True)
    ProjectDataGroup = InputSlot(stype='string', optional=True)
    WorkingDirectory = InputSlot(stype='filestring')
    DatasetRoles = InputSlot(stype='object')

    DatasetGroup = InputSlot(stype='object', level=1, optional=True) # Must mark as optional because not all subslots are required.

    # Outputs
    ImageGroup = OutputSlot(level=1)
    Image = OutputSlot() # The first dataset. Equivalent to ImageGroup[0]
    AllowLabels = OutputSlot(stype='bool') # Pulled from the first dataset only.

    _NonTransposedImageGroup = OutputSlot(level=1)

    # Must be the LAST slot declared in this class.
    # When the shell detects that this slot has been resized,
    #  it assumes all the others have already been resized.
    ImageName = OutputSlot() # Name of the first dataset is used.  Other names are ignored.
    
    def __init__(self, force5d=False, *args, **kwargs):
        super(OpDataSelectionGroup, self).__init__(*args, **kwargs)
        self._opDatasets = None
        self._roles = []
        self._force5d = force5d

        def handleNewRoles(*args):
            self.DatasetGroup.resize( len(self.DatasetRoles.value) )
        self.DatasetRoles.notifyReady( handleNewRoles )
        
    def setupOutputs(self):
        # Create internal operators
        if self.DatasetRoles.value != self._roles:
            self._roles = self.DatasetRoles.value
            # Clean up the old operators
            self.ImageGroup.disconnect()
            self.Image.disconnect()
            self._NonTransposedImageGroup.disconnect()
            if self._opDatasets is not None:
                self._opDatasets.cleanUp()
    
            self._opDatasets = OperatorWrapper( OpDataSelection, parent=self, operator_kwargs={ 'force5d' : self._force5d },
                                                broadcastingSlotNames=['ProjectFile', 'ProjectDataGroup', 'WorkingDirectory'] )
            self.ImageGroup.connect( self._opDatasets.Image )
            self._NonTransposedImageGroup.connect( self._opDatasets._NonTransposedImage )
            self._opDatasets.Dataset.connect( self.DatasetGroup )
            self._opDatasets.ProjectFile.connect( self.ProjectFile )
            self._opDatasets.ProjectDataGroup.connect( self.ProjectDataGroup )
            self._opDatasets.WorkingDirectory.connect( self.WorkingDirectory )

        if len( self._opDatasets.Image ) > 0:
            self.Image.connect( self._opDatasets.Image[0] )
            self.ImageName.connect( self._opDatasets.ImageName[0] )
            self.AllowLabels.connect( self._opDatasets.AllowLabels[0] )
        else:
            self.Image.disconnect()
            self.ImageName.disconnect()
            self.AllowLabels.disconnect()
            self.Image.meta.NOTREADY = True
            self.ImageName.meta.NOTREADY = True
            self.AllowLabels.meta.NOTREADY = True

    def execute(self, slot, subindex, rroi, result):
            assert False, "Unknown or unconnected output slot."

    def propagateDirty(self, slot, subindex, roi):
        # Output slots are directly connected to internal operators
        pass

class OpMultiLaneDataSelectionGroup( OpMultiLaneWrapper ):
    # TODO: Provide output slots DatasetsByRole and ImagesByRole as a convenience 
    #       to save clients the trouble of instantiating/using OpTransposeSlots.
    def __init__(self, force5d=False, *args, **kwargs):
        kwargs.update( { 'operator_kwargs' : {'force5d' : force5d},
                         'broadcastingSlotNames' : ['ProjectFile', 'ProjectDataGroup', 'WorkingDirectory', 'DatasetRoles'] } )
        super( OpMultiLaneDataSelectionGroup, self ).__init__(OpDataSelectionGroup, *args, **kwargs )
    
        # 'value' slots
        assert self.ProjectFile.level == 0
        assert self.ProjectDataGroup.level == 0
        assert self.WorkingDirectory.level == 0
        assert self.DatasetRoles.level == 0
        
        # Indexed by [lane][role]
        assert self.DatasetGroup.level == 2, "DatasetGroup is supposed to be a level-2 slot, indexed by [lane][role]"
    
    def addLane(self, laneIndex):
        """Reimplemented from base class."""
        numLanes = len(self.innerOperators)
        
        # Only add this lane if we don't already have it
        # We might be called from within the context of our own insertSlot signal.
        if numLanes == laneIndex:
            super( OpMultiLaneDataSelectionGroup, self ).addLane( laneIndex )

    def removeLane(self, laneIndex, finalLength):
        """Reimplemented from base class."""
        numLanes = len(self.innerOperators)
        if numLanes > finalLength:
            super( OpMultiLaneDataSelectionGroup, self ).removeLane( laneIndex, finalLength )








