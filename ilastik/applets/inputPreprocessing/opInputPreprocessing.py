from lazyflow.graph import Operator, InputSlot, OutputSlot
from lazyflow.operators.generic import OpSubRegion2
from lazyflow.roi import roiFromShape

class OpInputPreprocessing(Operator):
    Input = InputSlot()
    RawDatasetInfo = InputSlot() # The original dataset info object for this image.
    CropRoi = InputSlot(optional=True)
    #DownsampledShape = InputSlot(optional=True)
    
    CroppedImage = OutputSlot()
    Output = OutputSlot()
    
    def __init__(self, *args, **kwargs):
        super( OpInputPreprocessing, self ).__init__( *args, **kwargs )
        
        self._opSubRegion = OpSubRegion2( parent=self )
        self._opSubRegion.Input.connect( self.Input )
        self.CroppedImage.connect( self._opSubRegion.Output )

        # TODO: Insert downsampler...
        self.Output.connect( self._opSubRegion.Output )
        
    def setupOutputs(self):
        if self.CropRoi.ready():
            self._opSubRegion.Roi.setValue( self.CropRoi.value )
        else:
            shape = self.Input.meta.shape
            self._opSubRegion.Roi.setValue( roiFromShape( shape ) )

    def execute(self, slot, subindex, roi, result):
        assert False, "Shouldn't get here"

    def propagateDirty(self, slot, subindex, roi):
        pass
