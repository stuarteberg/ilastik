import collections
from PyQt4.QtCore import Qt, pyqtSignal
from PyQt4.QtGui import QSpinBox, QTableWidget, QTableWidgetItem, QSlider

class DownsampleDimensionsWidget( QTableWidget ):
    downsampled_shape_changed = pyqtSignal(object)

    def __init__(self, parent):
        super( DownsampleDimensionsWidget, self ).__init__(parent)
        self._original_shape = None
        self._downsampled_shape = None
        self._sliders = collections.OrderedDict()
    
    def init_ui(self):
        """
        This function is separate it can be called after the parent ui loads the .ui file.
        """
        self.setColumnCount( 3 )
        self.setHorizontalHeaderLabels(["old", "", "new"])
        
        self.resizeColumnsToContents()
        
    def reinit_contents(self, axes, original_shape, downsampled_shape):
        assert len(axes) == len(original_shape) == len(downsampled_shape)
        tagged_shape_original = collections.OrderedDict( zip(axes, original_shape) )
        tagged_shape_downsampled = collections.OrderedDict( zip(axes, downsampled_shape) )
        self.setRowCount( len(axes) )
        self.setVerticalHeaderLabels( list(axes) )

        for row, axis_key in enumerate(axes):
            original_size = tagged_shape_original[axis_key]
            downsampled_size = tagged_shape_downsampled[axis_key]

            # Size can be set with either a slider or a spinbox            
            slider = QSlider( Qt.Horizontal, parent=self )
            slider.setMinimum( 1 )
            slider.setMaximum( original_size )
            slider.setValue( downsampled_size )

            box = QSpinBox( parent=self )
            box.setMinimum( 1 )
            box.setMaximum( original_size )
            box.setValue( downsampled_size )

            # These connections auto-sync the slider and the box.
            slider.valueChanged.connect( box.setValue )
            box.valueChanged.connect( slider.setValue )
            
            # Also, emit a signal with the new shape
            # Connect to the box signal (not the slider),
            #  since that's what's used by the get_downsampled_shape() function
            def emit_shape():
                self.downsampled_shape_changed.emit( self.get_downsampled_shape() )
            box.valueChanged.connect( emit_shape )

            # Cannot downsample across channels or time.
            if axis_key == 'c' or axis_key == 't':
                box.setEnabled(False)
                slider.setEnabled(False)

            self.setItem( row, 0, QTableWidgetItem(str(original_size)) )
            self.setCellWidget( row, 1, slider )
            self.setCellWidget( row, 2, box )
        
        self.resizeColumnsToContents()

    def get_downsampled_shape(self):
        shape = []
        for row in range( self.rowCount() ):
            # Use box as the official reference.
            # See emit_shape(), above.
            box = self.cellWidget( row, 2 )
            shape.append( box.value() )
        return tuple(shape)

if __name__ == "__main__":
    from PyQt4.QtGui import QApplication
    
    app = QApplication([])
    w = DownsampleDimensionsWidget( None )
    w.reinit_contents( 'xyzc', (10,20,30,3), (5,15,30,3) )
    w.show()

    app.exec_()
