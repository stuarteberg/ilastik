from lazyflow.graph import Operator, InputSlot, OutputSlot
from lazyflow.operators.generic import OpSubRegion2
from lazyflow.operators import OpResize
from lazyflow.roi import roiFromShape

class OpInputPreprocessing(Operator):
    Input = InputSlot()
    RawDatasetInfo = InputSlot() # The original dataset info object for this image.
    CropRoi = InputSlot(optional=True)
    DownsampledShape = InputSlot(optional=True)
    
    CroppedImage = OutputSlot()
    DownsampledImage = OutputSlot()
    Output = OutputSlot()
    
    def __init__(self, *args, **kwargs):
        super( OpInputPreprocessing, self ).__init__( *args, **kwargs )
        
        self._opSubRegion = OpSubRegion2( parent=self )
        self._opSubRegion.Input.connect( self.Input )
        self.CroppedImage.connect( self._opSubRegion.Output )

        self._opResize = OpResize( parent=self )
        self._opResize.Input.connect( self._opSubRegion.Output )

        # These two outputs are synonyms for now.
        self.DownsampledImage.connect( self._opResize.Output )
        self.Output.connect( self._opResize.Output )
        
        self.progressSignal = self._opResize.progressSignal
        
    def setupOutputs(self):
        if self.CropRoi.ready():
            self._opSubRegion.Roi.setValue( self.CropRoi.value )
        else:
            shape = self.Input.meta.shape
            roi = roiFromShape( shape )
            roi = map( tuple, roi )
            self._opSubRegion.Roi.setValue( roi )
        
        if self.DownsampledShape.ready():
            self._opResize.ResizedShape.setValue( self.DownsampledShape.value )
        else:
            cropped_shape = self._opSubRegion.Output.meta.shape
            self._opResize.ResizedShape.setValue( cropped_shape )

    def execute(self, slot, subindex, roi, result):
        assert False, "Shouldn't get here"

    def propagateDirty(self, slot, subindex, roi):
        pass
