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
import threading
from functools import partial

import sip
from PyQt4 import uic
from PyQt4.QtGui import QApplication, QWidget, QIcon, QHeaderView, QStackedWidget, QTableWidgetItem, QPushButton, QMessageBox

from lazyflow.graph import Slot

from ilastik.utility import bind
from lazyflow.utility import PathComponents
from ilastik.utility.gui import ThreadRouter, threadRouted, ThunkEvent, ThunkEventHandler
from ilastik.shell.gui.iconMgr import ilastikIcons
from ilastik.applets.layerViewer.layerViewerGui import LayerViewerGui

from volumina.utility import decode_to_qstring

import logging
logger = logging.getLogger(__name__)

class Column():
    """Enum for table column positions"""
    Dataset = 0
    CropRegion = 1
    DownSampledSize = 2

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
        return self._viewerControlWidgetStack

    def setImageIndex(self, index):
        pass

    def stopAndCleanUp(self):
        for editor in self.layerViewerGuis.values():
            self.viewerStack.removeWidget( editor )
            editor.stopAndCleanUp()
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

        self.topLevelOperator.ExportPath.notifyInserted( bind( handleNewDataset ) )
        
        # For each dataset that already exists, update the GUI
        for i, subslot in enumerate(self.topLevelOperator.ExportPath):
            handleNewDataset( self.topLevelOperator.ExportPath, i )
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
                layerViewerGui = self.layerViewerGuis[imageSlot]
                self.viewerStack.removeWidget( layerViewerGui )
                self._viewerControlWidgetStack.removeWidget( layerViewerGui.viewerControlWidget() )
                layerViewerGui.stopAndCleanUp()

        self.topLevelOperator.Input.notifyRemove( bind( handleImageRemoved ) )
    
    def _initAppletDrawerUic(self):
        """
        Load the ui file for the applet drawer, which we own.
        """
        localDir = os.path.split(__file__)[0]
        drawerPath = os.path.join( localDir, "inputPreprocessingTableWidgetDrawer.ui")
        self.drawer = uic.loadUi(drawerPath)

    def initCentralUic(self):
        """
        Load the GUI from the ui file into this class and connect it with event handlers.
        """
        # Load the ui file into this class (find it in our own directory)
        localDir = os.path.split(__file__)[0]
        uic.loadUi(localDir+"/dataExport.ui", self)

        self.inputPreprocessingTableWidget.resizeRowsToContents()
        self.inputPreprocessingTableWidget.resizeColumnsToContents()
        self.inputPreprocessingTableWidget.setAlternatingRowColors(True)
        self.inputPreprocessingTableWidget.setShowGrid(False)
        self.inputPreprocessingTableWidget.horizontalHeader().setResizeMode(0, QHeaderView.Interactive)
        
        self.inputPreprocessingTableWidget.horizontalHeader().resizeSection(Column.Dataset, 200)
        self.inputPreprocessingTableWidget.horizontalHeader().resizeSection(Column.CropRegion, 250)
        self.inputPreprocessingTableWidget.horizontalHeader().resizeSection(Column.DownSampledSize, 100)

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
        self._viewerControlWidgetStack = QStackedWidget(parent=self)

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
        #FIXME
        return
    
        row = self.getSlotIndex( self.topLevelOperator.ExportPath, slot )
        assert row != -1, "Unknown input slot!"

        if not self.topLevelOperator.ExportPath[row].ready() or\
           not self.topLevelOperator.RawDatasetInfo[row].ready():
            return
        
        try:
            nickname = self.topLevelOperator.RawDatasetInfo[row].value.nickname
            exportPath = self.topLevelOperator.ExportPath[row].value
        except Slot.SlotNotReadyError:
            # Sadly, it is possible to get here even though we checked for .ready() immediately beforehand.
            # That's because the graph has a diamond-shaped DAG of connections, but the graph has no transaction mechanism
            # (It's therefore possible for RawDatasetInfo[row] to be ready() even though it's upstream partner is NOT ready.
            return
                
        self.inputPreprocessingTableWidget.setItem( row, Column.Dataset, QTableWidgetItem( decode_to_qstring(nickname) ) )
        self.inputPreprocessingTableWidget.setItem( row, Column.ExportLocation, QTableWidgetItem( decode_to_qstring(exportPath) ) )

        exportNowButton = QPushButton("Export")
        exportNowButton.setToolTip("Generate individual batch output dataset.")
        exportNowButton.clicked.connect( bind(self.exportResultsForSlot, self.topLevelOperator[row] ) )
        self.inputPreprocessingTableWidget.setCellWidget( row, Column.Action, exportNowButton )

        # Select a row if there isn't one already selected.
        selectedRanges = self.inputPreprocessingTableWidget.selectedRanges()
        if len(selectedRanges) == 0:
            self.inputPreprocessingTableWidget.selectRow(0)

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
        """
        Show the exported file in the viewer
        """
        # Get the selected row and corresponding slot value
        selectedRanges = self.inputPreprocessingTableWidget.selectedRanges()
        if len(selectedRanges) == 0:
            return
        row = selectedRanges[0].topRow()
        imageSlot = self.topLevelOperator.Input[row]
        
        # Create if necessary
        if imageSlot not in self.layerViewerGuis.keys():
            opLane = self.topLevelOperator.getLane(row)
            layerViewer = self.createLayerViewer(opLane)

            # Maximize the x-y view by default.
            layerViewer.volumeEditorWidget.quadview.ensureMaximized(2)
            
            self.layerViewerGuis[imageSlot] = layerViewer
            self.viewerStack.addWidget( layerViewer )
            self._viewerControlWidgetStack.addWidget( layerViewer.viewerControlWidget() )

        # Show the right one
        layerViewer = self.layerViewerGuis[imageSlot]
        self.viewerStack.setCurrentWidget( layerViewer )
        self._viewerControlWidgetStack.setCurrentWidget( layerViewer.viewerControlWidget() )


    def createLayerViewer(self, opLane):
        """
        This method provides an instance of LayerViewerGui for the given data lane.
        If this GUI class is subclassed, this method can be reimplemented to provide 
        custom layer types for the exported layers.
        """
        return InputPreprocessingLayerViewerGui(self.parentApplet, opLane)

class InputPreprocessingLayerViewerGui(LayerViewerGui):
    """
    Subclass the default LayerViewerGui implementation so we can provide a custom layer order.
    """

    def setupLayers(self):
        layers = []

        # Show the exported data on disk
        opLane = self.topLevelOperatorView
        exportedDataSlot = opLane.ImageOnDisk
        if exportedDataSlot.ready():
            exportLayer = self.createStandardLayerFromSlot( exportedDataSlot )
            exportLayer.name = "Exported Image (from disk)"
            exportLayer.visible = True
            exportLayer.opacity = 1.0
            layers.append(exportLayer)
        
        # Show the (live-updated) data we're exporting
        previewSlot = opLane.ImageToExport
        if previewSlot.ready():
            previewLayer = self.createStandardLayerFromSlot( previewSlot )
            previewLayer.name = "Live Preview"
            previewLayer.visible = False # off by default
            previewLayer.opacity = 1.0
            layers.append(previewLayer)

        rawSlot = opLane.FormattedRawData
        if rawSlot.ready():
            rawLayer = self.createStandardLayerFromSlot( rawSlot )
            rawLayer.name = "Raw Data"
            rawLayer.visible = True
            rawLayer.opacity = 1.0
            layers.append(rawLayer)

        return layers

    def determineDatashape(self):
        """Overridden from LayerViewerGui"""
        shape = None
        if self.topLevelOperatorView.ImageToExport.ready():
            shape = self.getVoluminaShapeForSlot(self.topLevelOperatorView.ImageToExport)
        elif self.topLevelOperatorView.FormattedRawData.ready():
            shape = self.getVoluminaShapeForSlot(self.topLevelOperatorView.FormattedRawData)
        return shape
            
            








