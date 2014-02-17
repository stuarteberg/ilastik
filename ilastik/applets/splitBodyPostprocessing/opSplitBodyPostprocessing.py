import collections
from functools import partial
import numpy
import vigra
import h5py
from lazyflow.graph import Operator, InputSlot, OutputSlot, OperatorWrapper
from lazyflow.roi import roiToSlice

from lazyflow.request import Request
from lazyflow.operators import OpFilterLabels, OpCompressedCache, OpVigraLabelVolume, OpMaskedWatershed, OpSelectLabel
from lazyflow.operators.ioOperators import OpH5WriterBigDataset
from lazyflow.operators.opReorderAxes import OpReorderAxes

from ilastik.applets.splitBodyCarving.opSplitBodyCarving import OpFragmentSetLut

from ilastik.utility import bind

import logging
logger = logging.getLogger(__name__)

class OpSplitBodyPostprocessing(Operator):
    
    RawData = InputSlot() # (Display only)
    
    InputData = InputSlot()
    RavelerLabels = InputSlot()
    MST = InputSlot()
    EditedRavelerBodyList = InputSlot() # The list of bodies actually edited
                                        # (Must be connected to ensure that setupOutputs will be 
                                        #   called resize the multi-slots when necessary)

    NavigationCoordinates = InputSlot(optional=True)
    
    # For these multislots, N = number of raveler bodies that were edited
    EditedRavelerBodies = OutputSlot(level=1)
    FragmentedBodies = OutputSlot(level=1)
    RelabeledFragments = OutputSlot(level=1)
    FilteredFragmentedBodies = OutputSlot(level=1) # Small CCs removed
    WatershedFilledBodies = OutputSlot(level=1) # (Fragmented, but with holes filled)
    
    FinalSegmentation = OutputSlot()

    # For serialization
    FinalSegmentationHdf5CacheInput = InputSlot(optional=True)
    FinalSegmentationHdf5CacheOutput = OutputSlot()
    FinalSegmentationCleanBlocks = OutputSlot()
    
    # Parse list of saved objects to determine list of raveler labels
    
    # For each raveler body:
    # - Generate seed image:
    #  - Overlay fragments (reverse order)
    #  - Run cc (labelImageWithBackground) on entire volume
    #  - Use OpFilterLabels to eliminate small pixels (set to 0)
    # - Run watershed:
    #  - seed image is as above
    #  - Boundary indicator is the pixel probabilities, but with all non-body pixels "masked out" by setting them to 2.0
    #  - Use terminate=StopAtThreshold, max_cost=2.0

    # Generate final volume:    
    # - Start with untouched raveler bodies
    # - Accumulate post-processed fragment images
    #  - relabel each fragment image (i.e. add a constant) to ensure no duplicate labels (including original raveler IDs!)

    #
    # RavelerLabels ------------------------> opSelectLabel ----->-------------------------------------------------------------------------------------------------------------------------------->---------------------------------------------------                                                
    #                                        /                    \                                                                                                                                \                                                  \
    # (each item in EditedRavelerBodyList) --                      \                                  --> FragmentedBodies                                                           -------------> opMaskedWatersheds --> opMaskedWatershedCaches --> opAccumulateFinalImage --> opFinalCache --> FinalSegmentation
    #                                        \                      \                                /                                                                              /              /                                                
    #                                         opFragmentSetLuts ---> opFragments --> opFragmentCaches --> opRelabelFragments --> opRelabeledFragmentCaches --> opSmallFragmentFilter   InputData --                                                
    #                                        /                      /                                                                                     \                         \                                                            
    # MST ---------------------------------->-----------------------                                                                                       \                         --> opFilteredFragmentCaches --> FilteredFragmentedBodies
    #                                                                                                                                                       \                                                                                    
    #                                                                                                                                                        --> RelabeledFragments                                                                
    

    def __init__(self, *args, **kwargs):
        super( OpSplitBodyPostprocessing, self ).__init__(*args, **kwargs)

        # HACK: Be sure that the output slots are resized if the raveler body list changes
        self.EditedRavelerBodyList.notifyDirty( bind(self._setupOutputs) )

        # Prepare a set of OpSelectLabels for easy access to raveler object masks
        self._opSelectLabel = OperatorWrapper( OpSelectLabel, parent=self, broadcastingSlotNames=['Input'] )
        self._opSelectLabel.Input.connect( self.RavelerLabels )
        self.EditedRavelerBodies.connect( self._opSelectLabel.Output )

        # Prepare a set of OpFragmentSetLuts to compute the lut of each body's fragments
        self._opFragmentSetLuts = OperatorWrapper( OpFragmentSetLut, parent=self, 
                                                   broadcastingSlotNames=['MST', 'CurrentEditingFragment', 'Trigger'] )
        self._opFragmentSetLuts.MST.connect( self.MST )
        self._opFragmentSetLuts.CurrentEditingFragment.setValue("")

        # Prepare a set of Fragment image generators
        self._opFragments = OperatorWrapper( OpFragment, parent=self, broadcastingSlotNames=['MST'] )
        self._opFragments.BodyMask.connect( self._opSelectLabel.Output )
        self._opFragments.FragmentLut.connect( self._opFragmentSetLuts.Lut )
        self._opFragments.MST.connect( self.MST )
        
        # Cache the fragment segmentations for each body
        self._opFragmentCaches = OperatorWrapper( OpCompressedCache, parent=self )
        self._opFragmentCaches.Input.connect( self._opFragments.Output )
        self.FragmentedBodies.connect( self._opFragmentCaches.Output )
        
        # CC is performed on the cached output, in part to ensure that the entire block is used.
        self._opRelabelFragments = OperatorWrapper( OpVigraLabelVolume, parent=self )
        self._opRelabelFragments.Input.connect( self._opFragmentCaches.Output )
        
        self._opRelabeledFragmentCaches = OperatorWrapper( OpCompressedCache, parent=self )
        self._opRelabeledFragmentCaches.Input.connect( self._opRelabelFragments.Output )
        self.RelabeledFragments.connect( self._opRelabeledFragmentCaches.Output )

        # Filter the small CC objects from the (relabeled) fragment segmentations
        self._opSmallFragmentFilter = OperatorWrapper( OpFilterLabels, parent=self, broadcastingSlotNames=['MinLabelSize'] )
        self._opSmallFragmentFilter.MinLabelSize.setValue( 50 )
        self._opSmallFragmentFilter.Input.connect( self._opRelabeledFragmentCaches.Output )

        self._opFilteredFragmentCaches = OperatorWrapper( OpCompressedCache, parent=self )
        self._opFilteredFragmentCaches.Input.connect( self._opSmallFragmentFilter.Output )
        self.FilteredFragmentedBodies.connect( self._opFilteredFragmentCaches.Output )

        # Watershed to fill the holes created by filtering.
        # Use a masked watershed to ensure that the watersheds stay within the bounds of the body
        self._opMaskedWatersheds =  OperatorWrapper( OpMaskedWatershed, parent=self )
        self._opMaskedWatersheds.Input.connect( self.InputData )
        self._opMaskedWatersheds.Mask.connect( self._opSelectLabel.Output )
        self._opMaskedWatersheds.Seeds.connect( self._opSmallFragmentFilter.Output )

        # Cache is necessary because it ensures that the entire volume is used for watershed.
        self._opMaskedWatershedCaches = OperatorWrapper( OpCompressedCache, parent=self )
        self._opMaskedWatershedCaches.Input.connect( self._opMaskedWatersheds.Output )
        self.WatershedFilledBodies.connect( self._opMaskedWatershedCaches.Output )

        self._opAccumulateFinalImage = OpAccumulateFragmentSegmentations( parent=self )
        self._opAccumulateFinalImage.RavelerLabels.connect( self.RavelerLabels )
        self._opAccumulateFinalImage.FragmentSegmentations.connect( self.WatershedFilledBodies )
        
        self._opFinalCache = OpCompressedCache( parent=self )
        self._opFinalCache.Input.connect( self._opAccumulateFinalImage.Output )
        self.FinalSegmentation.connect( self._opFinalCache.Output )

        # Cache serialization slots
        self._opFinalCache.InputHdf5.connect( self.FinalSegmentationHdf5CacheInput )
        self.FinalSegmentationCleanBlocks.connect( self._opFinalCache.CleanBlocks )
        self.FinalSegmentationHdf5CacheOutput.connect( self._opFinalCache.OutputHdf5 )
        
    def setupOutputs(self):
        raveler_bodies = self.EditedRavelerBodyList.value
        num_bodies = len(raveler_bodies)

        # Map raveler body ids to the subslots that need them.
        self._opSelectLabel.SelectedLabel.resize( num_bodies )
        self._opFragmentSetLuts.RavelerLabel.resize( num_bodies )
        for index, raveler_body_id in enumerate(raveler_bodies):
            self._opSelectLabel.SelectedLabel[index].setValue( raveler_body_id )
            self._opFragmentSetLuts.RavelerLabel[index].setValue( raveler_body_id )

    def execute(self, slot, subindex, roi, result):
        # All outputs are provided by internal operators, so this function should never be called
        assert False, "Unknown output slot: {}".format( slot.name )

    def propagateDirty(self, slot, subindex, roi):
        if slot == self.NavigationCoordinates:
            pass
        else:
            # If anything is dirty, the entire output is dirty
            self.FinalSegmentation.setDirty()
    
    def exportFinalSegmentation(self, outputPath, axisorder, progressCallback=None):
        assert self.FinalSegmentation.ready(), "Can't export yet: The final segmentation isn't ready!"

        logger.info("Starting Final Segmentation Export...")
        
        opTranspose = OpReorderAxes( parent=self )
        opTranspose.AxisOrder.setValue( axisorder )
        opTranspose.Input.connect( self.FinalSegmentation )
        
        f = h5py.File(outputPath, 'w')
        opExporter = OpH5WriterBigDataset(parent=self)
        opExporter.hdf5File.setValue( f )
        opExporter.hdf5Path.setValue( 'split_result' )
        opExporter.Image.connect( opTranspose.Output )
        if progressCallback is not None:
            opExporter.progressSignal.subscribe( progressCallback )
        
        req = Request( partial(self._runExporter, opExporter) )

        def cleanOps():
            opExporter.cleanUp()
            opTranspose.cleanUp()
        
        def handleFailed( exc, exc_info ):
            cleanOps()        
            f.close()
            import traceback
            traceback.print_tb(exc_info[2])
            msg = "Final Segmentation export FAILED due to the following error:\n{}".format( exc )
            logger.error( msg )

        def handleFinished( result ):
            try:
                cleanOps()
                logger.info("FINISHED Final Segmentation Export")
            finally:
                f.close()

        def handleCancelled():
            cleanOps()
            f.close()
            logger.info( "Final Segmentation export was cancelled!" )

        req.notify_failed( handleFailed )
        req.notify_finished( handleFinished )
        req.notify_cancelled( handleCancelled )
        
        req.submit()
        return req # Returned in case the user wants to cancel it.

    def _runExporter(self, opExporter):
        # Trigger the export
        success = opExporter.WriteImage.value
        assert success
        return success
    
    def setInSlot(self, slot, subindex, roi, value):
        assert slot == self.FinalSegmentationHdf5CacheInput, "Invalid slot for setInSlot(): {}".format( slot.name )
        # Nothing to do here.
        # Our Input slots are directly fed into the cache, 
        #  so all calls to __setitem__ are forwarded automatically 
    
class OpFragment(Operator):
    BodyMask = InputSlot()
    FragmentLut = InputSlot()
    MST = InputSlot()
    
    Output = OutputSlot()
    
    def setupOutputs(self):
        self.Output.meta.assignFrom( self.BodyMask.meta )
    
    def execute(self, slot, subindex, roi, result):
        assert slot == self.Output
        # Start with the original raveler object
        self.BodyMask(roi.start, roi.stop).writeInto(result).wait()

        lut = self.FragmentLut[:].wait()
        mst = self.MST.value

        slicing = roiToSlice( roi.start[1:4], roi.stop[1:4] )
        a = result[0,...,0]
        b = lut[mst.regionVol[slicing]] # (Advanced indexing)

        # Use bitwise_and instead of numpy.where to avoid the temporary caused by a == 0
        #a[:] = numpy.where( a == 0, 0, b )
        assert result.dtype == numpy.uint8, "This code assumes uint8 as the dtype!"
        a[:] *= 0xFF # Assumes uint8
        numpy.bitwise_and( a, b, out=a )
        return result

    def propagateDirty(self, slot, subindex, roi):
        self.Output.setDirty()

class OpAccumulateFragmentSegmentations( Operator ):
    RavelerLabels = InputSlot()
    FragmentSegmentations = InputSlot(level=1)
    
    Output = OutputSlot()
    Mapping = OutputSlot()

    def __init__(self, *args, **kwargs):
        super( OpAccumulateFragmentSegmentations, self ).__init__( *args, **kwargs )
        self._mapping = None
    
    def setupOutputs(self):
        self.Output.meta.assignFrom( self.RavelerLabels.meta )
        self.Mapping.meta.dtype = object
        self.Mapping.meta.shape = (1,)

    def execute(self, slot, subindex, roi, result):
        if slot == self.Mapping:
            result[0] = self._mapping
            return result
        elif slot == self.Output:
            assert (roi.start == 0).all() and (roi.stop == self.Output.meta.shape).all(), "Must request entire image."
            self.RavelerLabels(roi.start, roi.stop).writeInto( result ).wait()
    
            # Allocate a temporary for our fragment images
            fragment_image = numpy.zeros( result.shape, dtype=numpy.int32 )
            max_label = result.max()
            self._mapping = collections.OrderedDict()
            self._mapping[(0,max_label+1)] = -1 # Special body-id: -1 means "identity"
    
            for body_index, slot in enumerate(self.FragmentSegmentations):
                slot(roi.start, roi.stop).writeInto(fragment_image.view(numpy.uint32)).wait()

                # This next line shows what we want to do, but it creates a big 
                # temporary array (e.g. fragment_image + max_label)
                # fragment_image = numpy.where( fragment_image, fragment_image+max_label, 0) 

                # Instead, we bend over backwards here to do this 'in place'
                logger.info( "Adding body {} to final image.".format( body_index ) )
                fragment_image[:] = numpy.where( fragment_image, fragment_image, -max_label )
                numpy.add( fragment_image, max_label, out=fragment_image )
                result[:] = numpy.where( fragment_image, fragment_image, result )
                
                logger.info( "Finding new max label..." )
                # New max
                max_label = result.max()
                
                # Update mapping
                old_max = self._mapping.keys()[-1][1]
                body_id = slot.meta.selected_label
                self._mapping[(old_max,max_label+1)] = body_id

            logger.info( "Finished assembling final segmentation." )
            return result
        else:
            assert False, "Unknown output slot: {}".format( slot.name )

    def propagateDirty(self, slot, subindex, roi):
        self.Output.setDirty()























