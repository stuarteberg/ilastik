from lazyflow.graph import Operator, InputSlot, OutputSlot

from ilastik.applets.base.applet import DatasetConstraintError

class OpLayerViewer(Operator):
    """
    This is the default top-level operator for the layer-viewer class.
    Note that applets based on the LayerViewer applet (and the LayerViewerGui) do NOT need to use this operator.
    Any operator will work with the LayerViewerGui base class.
    """
    name = "OpLayerViewer"
    category = "top-level"

    RawInput = InputSlot()
    OtherInput = InputSlot(optional=True)
    
    NumChannels = InputSlot(optional=True)
    Output = OutputSlot()

    def __init__(self, *args, **kwargs):
        super( OpLayerViewer, self ).__init__(*args, **kwargs)
        
        self.RawInput.notifyReady( self.checkConstraints )
        self.OtherInput.notifyReady( self.checkConstraints )

    def setupOutputs(self):
        if self.OtherInput.ready():
            self.Output.meta.assignFrom( self.OtherInput.meta )
            if self.NumChannels.ready():
                tagged_shape = self.Output.meta.getTaggedShape()
                tagged_shape['c'] = self.NumChannels.value
                self.Output.meta.shape = tuple( tagged_shape.values() )
        else:
            self.Output.meta.NOTREADY = True
        
    def execute(self, slot, subindex, rroi, result):
        result[:] = self.OtherInput[rroi.toSlice()].wait()
        return result

    def propagateDirty(self, slot, subindex, roi):
        if slot == self.OtherInput:
            self.Output.setDirty( roi )
    
    def checkConstraints(self, *args):
        """
        Example of how to check input data constraints.
        """
        if self.RawInput.ready():
            numChannels = self.RawInput.meta.getTaggedShape()['c']
            if numChannels != 1:
                raise DatasetConstraintError(
                    "Layer Viewer",
                    "Raw data must have exactly one channel.  " +
                    "You attempted to add a dataset with {} channels".format( numChannels ) )

        if self.OtherInput.ready() and self.RawInput.ready():
            rawTaggedShape = self.RawInput.meta.getTaggedShape()
            otherTaggedShape = self.OtherInput.meta.getTaggedShape()
            rawTaggedShape['c'] = None
            otherTaggedShape['c'] = None
            if dict(rawTaggedShape) != dict(otherTaggedShape):
                msg = "Raw data and other data must have equal dimensions (different channels are okay).\n"\
                      "Your datasets have shapes: {} and {}".format( self.RawInput.meta.shape, self.OtherInput.meta.shape )
                raise DatasetConstraintError( "Layer Viewer", msg )
        
        