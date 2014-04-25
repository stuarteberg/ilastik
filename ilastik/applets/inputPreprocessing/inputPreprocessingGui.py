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

import os
from functools import partial
import collections

import sip
from PyQt4 import uic
from PyQt4.QtCore import Qt
from PyQt4.QtGui import QApplication, QWidget, QHeaderView, QTableWidgetItem, QCheckBox, QListWidget

from lazyflow.graph import Slot

from ilastik.utility import bind
from lazyflow.roi import roiFromShape
from ilastik.utility.gui import ThreadRouter, threadRouted, ThunkEvent, ThunkEventHandler
from ilastik.applets.layerViewer.layerViewerGui import LayerViewerGui

from volumina.utility import decode_to_qstring

import logging
logger = logging.getLogger(__name__)

class Column():
    """Enum for table column positions"""
    Dataset = 0
    ApplyCrop = 1
    CropRoi = 2
    ApplyDownsample = 3
    DownsampledSize = 4

class Stage():
    INPUT = 0
    CROPPED = 1
    #DOWNSAMPLED = 2

class InputPreprocessingGui(QWidget):
    """
    Manages all GUI elements in the data selection applet.
    This class itself is the central widget and also owns/manages the applet drawer widgets.
    """
    ###########################################
    ### AppletGuiInterface Concrete Methods ###
    ###########################################
    
    def centralWidget( self ):
        return self

    def appletDrawer(self):
        return self.drawer

    def menus( self ):
        return []

    def viewerControlWidget(self):
        return self._viewerControlWidget

    def setImageIndex(self, index):
        pass

    def stopAndCleanUp(self):
        for viewer_dict in self.layerViewerGuis.values():
            for viewer in viewer_dict.values():
                self.viewerStack.removeWidget( viewer )
                viewer.stopAndCleanUp()
        self.layerViewerGuis.clear()

    def imageLaneAdded(self, laneIndex):
        pass

    def imageLaneRemoved(self, laneIndex, finalLength):
        pass

    ###########################################
    ###########################################
    
    def __init__(self, parentApplet, topLevelOperator):
        super(InputPreprocessingGui, self).__init__()

        self.drawer = None
        self.topLevelOperator = topLevelOperator

        self.threadRouter = ThreadRouter(self)
        self._thunkEventHandler = ThunkEventHandler(self)
        
        self._initAppletDrawerUic()
        self.initCentralUic()
        self.initViewerControls()
        
        self.parentApplet = parentApplet
        self.progressSignal = parentApplet.progressSignal
        
        self.layerViewerGuis = {}
        self._display_stage = Stage.INPUT
        
        def handleNewDataset( multislot, index ):
            # Make room in the GUI table
            self.inputPreprocessingTableWidget.insertRow( index )
            
            # Update the table row data when this slot has new data
            # We can't bind in the row here because the row may change in the meantime.
            multislot[index].notifyReady( bind( self.updateTableForSlot ) )
            if multislot[index].ready():
                self.updateTableForSlot( multislot[index] )

            multislot[index].notifyUnready( self._handleReadyStatusChange )
            multislot[index].notifyReady( self._handleReadyStatusChange )

        self.topLevelOperator.Output.notifyInserted( bind( handleNewDataset ) )
        
        # For each dataset that already exists, update the GUI
        for i, subslot in enumerate(self.topLevelOperator.Output):
            handleNewDataset( self.topLevelOperator.Output, i )
            if subslot.ready():
                self.updateTableForSlot(subslot)
    
        def handleImageRemoved( multislot, index, finalLength ):
            if self.inputPreprocessingTableWidget.rowCount() <= finalLength:
                return

            # Remove the row we don't need any more
            self.inputPreprocessingTableWidget.removeRow( index )

            # Remove the viewer for this dataset
            imageSlot = self.topLevelOperator.Input[index]
            if imageSlot in self.layerViewerGuis.keys():
                viewer_dict = self.layerViewerGuis[imageSlot]
                for layerViewerGui in viewer_dict.values():
                    self.viewerStack.removeWidget( layerViewerGui )
                    layerViewerGui.stopAndCleanUp()
                viewer_dict.clear()
                del self.layerViewerGuis[imageSlot]

        self.topLevelOperator.Input.notifyRemove( bind( handleImageRemoved ) )
    
    def _initAppletDrawerUic(self):
        """
        Load the ui file for the applet drawer, which we own.
        """
        localDir = os.path.split(__file__)[0]
        drawerPath = os.path.join( localDir, "inputPreprocessingDrawer.ui")
        self.drawer = uic.loadUi(drawerPath)

    def initCentralUic(self):
        """
        Load the GUI from the ui file into this class and connect it with event handlers.
        """
        # Load the ui file into this class (find it in our own directory)
        localDir = os.path.split(__file__)[0]
        uic.loadUi(localDir+"/inputPreprocessingCentralWidget.ui", self)

        self.inputPreprocessingTableWidget.resizeRowsToContents()
        self.inputPreprocessingTableWidget.resizeColumnsToContents()
        self.inputPreprocessingTableWidget.setAlternatingRowColors(True)
        self.inputPreprocessingTableWidget.setShowGrid(False)
        self.inputPreprocessingTableWidget.horizontalHeader().setResizeMode(0, QHeaderView.Interactive)
        
        self.inputPreprocessingTableWidget.horizontalHeader().resizeSection(Column.Dataset, 200)
        self.inputPreprocessingTableWidget.horizontalHeader().resizeSection(Column.ApplyCrop, 200)
        self.inputPreprocessingTableWidget.horizontalHeader().resizeSection(Column.CropRoi, 250)
        self.inputPreprocessingTableWidget.horizontalHeader().resizeSection(Column.ApplyDownsample, 100)
        self.inputPreprocessingTableWidget.horizontalHeader().resizeSection(Column.DownsampledSize, 100)

        self.inputPreprocessingTableWidget.verticalHeader().hide()

        # Set up handlers
        self.inputPreprocessingTableWidget.itemSelectionChanged.connect(self.handleTableSelectionChange)

        # Set up the viewer area
        self.initViewerStack()
        self.splitter.setSizes([150, 850])
    
    def initViewerStack(self):
        self.layerViewerGuis = {}
        self.viewerStack.addWidget( QWidget() )
        
    def initViewerControls(self):
        self._viewerControlWidget = uic.loadUi(os.path.split(__file__)[0] + "/viewerControls.ui")
        list_widget = self._viewerControlWidget.stageLayerListWidget
        list_widget.addItems( ["Input", "Cropped"] )
        list_widget.setSelectionMode( QListWidget.SingleSelection )

        def handleSelectionChanged(row):
            self._display_stage = row
            self.showSelectedDataset()
        list_widget.currentRowChanged.connect( handleSelectionChanged )

    def getSlotIndex(self, multislot, subslot ):
        # Which index is this slot?
        for index, slot in enumerate(multislot):
            if slot == subslot:
                return index
        return -1

    @threadRouted
    def updateTableForSlot(self, slot):
        """
        Update the table row that corresponds to the given slot of the top-level operator (could be either input slot)
        """
        row = self.getSlotIndex( self.topLevelOperator.Output, slot )
        assert row != -1, "Unknown input slot!"

        if not self.topLevelOperator.Output[row].ready() or\
           not self.topLevelOperator.RawDatasetInfo[row].ready():
            return

        opLane = self.topLevelOperator.getLane(row)
        
        try:
            nickname = opLane.RawDatasetInfo.value.nickname
            apply_crop = opLane.CropRoi.ready()
            if apply_crop:
                crop_roi = opLane.CropRoi.value
                crop_roi_str = str(tuple(crop_roi[0])) + " : " + str(tuple(crop_roi[1]))
            else:
                crop_roi_str = ""
            
            # TODO: Downsampling
            
        except Slot.SlotNotReadyError:
            # Sadly, it is possible to get here even though we checked for .ready() immediately beforehand.
            # That's because the graph has a diamond-shaped DAG of connections, but the graph has no transaction mechanism
            # (It's therefore possible for RawDatasetInfo[row] to be ready() even though it's upstream partner is NOT ready.
            return
        
        crop_checkbox = QCheckBox()
        crop_checkbox.setChecked( apply_crop )
        crop_checkbox.toggled.connect( partial(self._handleCropCheckboxToggled, opLane) )
        
        self.inputPreprocessingTableWidget.setItem( row, Column.Dataset, QTableWidgetItem( decode_to_qstring(nickname) ) )
        self.inputPreprocessingTableWidget.setItem( row, Column.CropRoi, QTableWidgetItem( crop_roi_str ) )

        self.inputPreprocessingTableWidget.setCellWidget( row, Column.ApplyCrop, crop_checkbox )

        # Select a row if there isn't one already selected.
        selectedRanges = self.inputPreprocessingTableWidget.selectedRanges()
        if len(selectedRanges) == 0:
            self.inputPreprocessingTableWidget.selectRow(0)

    def _handleCropCheckboxToggled(self, opLane, checked):
        if checked:
            opLane.CropRoi.setValue( roiFromShape( opLane.Input.meta.shape ) )
        else:
            opLane.CropRoi.disconnect()

        # refresh
        self.updateTableForSlot(opLane.Output)
        self.showSelectedDataset()
        

    def setEnabledIfAlive(self, widget, enable):
        if not sip.isdeleted(widget):
            widget.setEnabled(enable)
    
    def _handleReadyStatusChange(self, *args):
        """Called when at least one dataset became 'unready', so we have to disable the export button."""
        # FIXME
        return
        all_ready = True
        # Enable/disable the appropriate export buttons in the table.
        # Use ThunkEvents to ensure that this happens in the Gui thread.        
        for row, slot in enumerate( self.topLevelOperator.ImageToExport ):
            all_ready &= slot.ready()
            export_button = self.inputPreprocessingTableWidget.cellWidget( row, Column.Action )
            if export_button is not None:
                executable_event = ThunkEvent( partial(self.setEnabledIfAlive, export_button, slot.ready()) )
                QApplication.instance().postEvent( self, executable_event )

        # Disable the "Export all" button unless all slots are ready.
        executable_event = ThunkEvent( partial(self.setEnabledIfAlive, self.drawer.exportAllButton, all_ready) )
        QApplication.instance().postEvent( self, executable_event )

    def handleTableSelectionChange(self):
        """
        Any time the user selects a new item, select the whole row.
        """
        self.selectEntireRow()
        self.showSelectedDataset()
    
    def selectEntireRow(self):
        # FIXME: There is a better way to do this...
        # Figure out which row is selected
        selectedItemRows = set()
        selectedRanges = self.inputPreprocessingTableWidget.selectedRanges()
        for rng in selectedRanges:
            for row in range(rng.topRow(), rng.bottomRow()+1):
                selectedItemRows.add(row)
        
        # Disconnect from selection change notifications while we do this
        self.inputPreprocessingTableWidget.itemSelectionChanged.disconnect( self.handleTableSelectionChange )
        for row in selectedItemRows:
            self.inputPreprocessingTableWidget.selectRow(row)

        # Reconnect now that we're finished
        self.inputPreprocessingTableWidget.itemSelectionChanged.connect(self.handleTableSelectionChange)
        
    def showSelectedDataset(self):
        # Get the selected row and corresponding slot value
        selectedRanges = self.inputPreprocessingTableWidget.selectedRanges()
        if len(selectedRanges) == 0:
            return
        row = selectedRanges[0].topRow()
        imageSlot = self.topLevelOperator.Input[row]
        
        # Create if necessary
        opLane = self.topLevelOperator.getLane(row)
        if imageSlot not in self.layerViewerGuis.keys():
            self.layerViewerGuis[imageSlot] = {}
        
        # Create if necessary
        if self._display_stage not in self.layerViewerGuis[imageSlot]:
            layerViewer = self.createLayerViewer(opLane, self._display_stage)
            self.layerViewerGuis[imageSlot][self._display_stage] = layerViewer
            self.viewerStack.addWidget( layerViewer )
            if self._display_stage == Stage.INPUT:
                layerViewer.editor.cropModel.changed.connect( partial(self._handleCropChange, opLane) )

            # Enable/disable cropping
            if self._display_stage == Stage.INPUT and opLane.CropRoi.ready():
                crop_extents_3d = _get_crop_extents(opLane)
                layerViewer.editor.cropModel.set_crop_extents( crop_extents_3d )

        # Show the viewer
        layerViewer = self.layerViewerGuis[imageSlot][self._display_stage]
        self.viewerStack.setCurrentWidget( layerViewer )
        self.refreshViewerControls(row)
        
        # Enable/disable crop lines
        show_croplines = (self._display_stage == Stage.INPUT and opLane.CropRoi.ready())
        layerViewer.editor.showCropLines( show_croplines )

    def _handleCropChange( self, opLane, crop_extents_model ):
        if not opLane.CropRoi.ready():
            return
        old_roi = opLane.CropRoi.value
        old_extents = map(list, zip(*old_roi))

        new_roi_3d = crop_extents_model.get_roi_3d()

        # FIXME: doesn't work for 2D.
        axes = opLane.Input.meta.getAxisKeys()
        old_extents[ axes.index('x') ][0] = new_roi_3d[0][0]
        old_extents[ axes.index('y') ][0] = new_roi_3d[0][1]
        old_extents[ axes.index('z') ][0] = new_roi_3d[0][2]
        old_extents[ axes.index('x') ][1] = new_roi_3d[1][0]
        old_extents[ axes.index('y') ][1] = new_roi_3d[1][1]
        old_extents[ axes.index('z') ][1] = new_roi_3d[1][2]
        
        new_roi = zip( *old_extents )
        opLane.CropRoi.setValue( new_roi )

        # Update the table
        crop_roi_str = str(tuple(new_roi[0])) + " : " + str(tuple(new_roi[1]))
        row = opLane.current_view_index()
        self.inputPreprocessingTableWidget.setItem( row, Column.CropRoi, QTableWidgetItem( crop_roi_str ) )

        # Find the layerviewer that shows the cropped result and update it now
        # (Normally, it doesn't look for changes in datashape)
        if opLane.Input in self.layerViewerGuis and \
           Stage.CROPPED in self.layerViewerGuis[opLane.Input]:
            self.layerViewerGuis[opLane.Input][Stage.CROPPED].updateAllLayers()        

    def refreshViewerControls(self, lane_index):
        list_widget = self._viewerControlWidget.stageLayerListWidget
        def setItemEnabled(item_row, enabled):
            item = list_widget.item(item_row)
            flags = item.flags()
            if enabled:
                flags |= Qt.ItemIsEnabled
            else:
                flags &= ~Qt.ItemIsEnabled
            item.setFlags( flags )

        opLane = self.topLevelOperator.getLane(lane_index)
        if not opLane.CroppedImage.ready() and list_widget.selectedIndexes()[0] == Stage.CROPPED:
            list_widget.item(Stage.INPUT).setSelected(True)
        
        setItemEnabled( Stage.INPUT, opLane.Input.ready() )
        setItemEnabled( Stage.CROPPED, opLane.CroppedImage.ready() )
        #setItemEnabled( Stage.DOWNSAMPLED, opLane.Output.ready() )

    def createLayerViewer(self, opLane, stage):
        """
        This method provides an instance of LayerViewerGui for the given data lane.
        """
        return InputPreprocessingLayerViewerGui(stage, self.parentApplet, opLane)

def _get_crop_extents(opLane):
    # The volume editor crop model needs extents in xyz order (3d only),
    if opLane.CropRoi.ready():
        crop_roi = opLane.CropRoi.value
    else:
        crop_roi = roiFromShape( opLane.Input.meta.shape )
    axes = opLane.Input.meta.getAxisKeys()
    tagged_roi_start = collections.OrderedDict( zip(axes, crop_roi[0]) )
    tagged_roi_stop = collections.OrderedDict( zip(axes, crop_roi[1]) )
    crop_extents_3d = [ ( tagged_roi_start['x'], tagged_roi_stop['x'] ),
                        ( tagged_roi_start['y'], tagged_roi_stop['y'] ),
                        ( tagged_roi_start['z'], tagged_roi_stop['z'] ) ]
    return crop_extents_3d

class InputPreprocessingLayerViewerGui(LayerViewerGui):
    """
    Subclass the default LayerViewerGui implementation so we can provide a custom layer order.
    """
    
    def __init__(self, stage, *args, **kwargs):
        super( InputPreprocessingLayerViewerGui, self ).__init__( *args, **kwargs )
        self._stage = stage
    
    def setupLayers(self):
        layers = []
        opLane = self.topLevelOperatorView

        if self._stage == Stage.INPUT:
            # Show the exported data on disk
            if opLane.Input.ready():
                inputLayer = self.createStandardLayerFromSlot( opLane.Input )
                inputLayer.name = "Input Data"
                inputLayer.visible = True
                inputLayer.opacity = 1.0
                layers.append(inputLayer)
                
                crop_extents_3d = _get_crop_extents(opLane)
                self.editor.cropModel.set_crop_extents( crop_extents_3d )
        
        if self._stage == Stage.CROPPED:
            # Show the exported data on disk
            if opLane.CroppedImage.ready():
                croppedLayer = self.createStandardLayerFromSlot( opLane.CroppedImage )
                croppedLayer.name = "Cropped data"
                croppedLayer.visible = True
                croppedLayer.opacity = 1.0
                layers.append(croppedLayer)

        # TODO
        #if self._stage == self.SHOW_DOWNAMPLED

        return layers

    def determineDatashape(self):
        """Overridden from LayerViewerGui"""
        shape = None
        if self._stage == Stage.INPUT and self.topLevelOperatorView.Input.ready():
            shape = self.getVoluminaShapeForSlot(self.topLevelOperatorView.Input)
        elif self._stage == Stage.CROPPED and self.topLevelOperatorView.CroppedImage.ready():
            shape = self.getVoluminaShapeForSlot(self.topLevelOperatorView.CroppedImage)
        return shape
