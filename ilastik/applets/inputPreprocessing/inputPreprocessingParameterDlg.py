import numpy

from PyQt4 import uic
from PyQt4.QtGui import QDialog

class ParameterWidget(QDialog):

    def __init__(self, parent, opInputPreprocessing):
        super( ParameterWidget, self ).__init__(parent)
        self._op = opInputPreprocessing
        uic.loadUi( 'parameterWidget.ui', self )
        self._initSubregionWidget()
        self._initDownsampleWidget()

    def _initSubregionWidget(self):
        op = self._op
        shape = op.Input.meta.shape
        inputAxes = op.Input.meta.getAxisKeys()
        
        if op.CropRoi.ready():
            start, stop = op.CropRoi.value
        else:
            start = (None,) * len( shape )
            stop = (None,) * len( shape )
        
        self.roiWidget.initWithExtents( inputAxes, shape, start, stop )

        def _handleRoiChange(newstart, newstop):
            # Configure the operator for the new subregion.
            # Replace 'None' values with 0/max
            shape = op.Input.meta.shape
            start = map( lambda a: a or 0, newstart )
            stop = map( lambda (a,b): a or b, zip(newstop, shape) )
            start, stop = tuple(start), tuple(stop)
            op.CropRoi.setValue( (start, stop) )
        self.roiWidget.roiChanged.connect( _handleRoiChange )

        self.cropGroupBox.setChecked( op.CropRoi.ready() )
        def _handleCropToggled(checked):
            if not checked:
                op.CropRoi.disconnect()
            else:
                _handleRoiChange( *self.roiWidget.roi )
        self.cropGroupBox.toggled.connect( _handleCropToggled )

    def _initDownsampleWidget(self):
        op = self._op
        
        # Prepare for future crop changes.
        def _handleDownsampleInputChange( *args ):
            axes = op.Input.meta.getAxisKeys()
            if op.CroppedImage.ready():
                original_shape = op.CroppedImage.meta.shape
            else:
                original_shape = op.Input.meta.shape

            if op.DownsampledShape.ready():
                downsampled_shape = op.DownsampledShape.value
            else:
                downsampled_shape = original_shape
            self.downsampleWidget.reinit_contents( axes, original_shape, downsampled_shape )
        op.CroppedImage.notifyMetaChanged( _handleDownsampleInputChange )
        op.CroppedImage.notifyReady( _handleDownsampleInputChange )
        op.CroppedImage.notifyUnready( _handleDownsampleInputChange )

        # initial setup
        _handleDownsampleInputChange()

        def _handleDownsampleShapeChanged( new_shape ):
            op.DownsampledShape.setValue( new_shape )
        self.downsampleWidget.downsampled_shape_changed.connect( _handleDownsampleShapeChanged )

        self.downsampleGroupBox.setChecked( op.DownsampledShape.ready() )
        def _handleDownsampleToggled(checked):
            if not checked:
                op.DownsampledShape.disconnect()
            else:
                _handleDownsampleShapeChanged( self.downsampleWidget.get_downsampled_shape() )
        self.downsampleGroupBox.toggled.connect( _handleDownsampleToggled )

#**************************************************************************
# Quick debug
#**************************************************************************
if __name__ == "__main__":
    import vigra
    from PyQt4.QtGui import QApplication
    from lazyflow.graph import Graph
    from opInputPreprocessing import OpInputPreprocessing

    data = numpy.zeros( (10,20,30,3), dtype=numpy.float32 )
    data = vigra.taggedView(data, 'xyzc')

    op = OpInputPreprocessing( graph=Graph() )
    op.Input.setValue( data )
    op.RawDatasetInfo.setValue(1)
    assert op.CroppedImage.ready()

    app = QApplication([])
    w = ParameterWidget(None, op)
    w.show()
    
    app.exec_()
    