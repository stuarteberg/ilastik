from lazyflow.graph import Operator, InputSlot, OutputSlot
from lazyflow.operators.generic import OpSubRegion2

class OpInputPreprocessing(Operator):
    Input = InputSlot()
    CropRoi = InputSlot()
    #DownsampledShape = InputSlot(optional=True)
    
    CroppedImage = OutputSlot()
    Output = OutputSlot()
    
    def __init__(self, *args, **kwargs):
        super( OpInputPreprocessing, self ).__init__( *args, **kwargs )
        
        self._opSubRegion = OpSubRegion2( parent=self )
        self._opSubRegion.Input.connect( self.Input )
        self._opSubRegion.Roi.connect( self.CropRoi )
        self.CroppedImage.connect( self._opSubRegion.Output )

        # TODO: Insert downsampler...
        self.Output.connect( self._opSubRegion.Output )
        
    def setupOutputs(self):
        pass

    def execute(self, slot, subindex, roi, result):
        assert False, "Shouldn't get here"

    def propagateDirty(self, slot, subindex, roi):
        pass
