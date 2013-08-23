import os
import threading
from functools import partial

from PyQt4 import uic
from PyQt4.QtGui import QApplication, QWidget, QIcon, QHeaderView, QStackedWidget, QTableWidgetItem, QPushButton, QMessageBox

from lazyflow.graph import Slot

import ilastik.applets.base.applet
from ilastik.utility import bind, PathComponents
from ilastik.utility.gui import ThreadRouter, threadRouted, ThunkEvent, ThunkEventHandler
from ilastik.shell.gui.iconMgr import ilastikIcons
from ilastik.applets.layerViewer.layerViewerGui import LayerViewerGui

from opDataExport import get_model_op
from volumina.widgets.dataExportOptionsDlg import DataExportOptionsDlg

import logging
logger = logging.getLogger(__name__)

class Column():
    """ Enum for table column positions """
    Dataset = 0
    ExportLocation = 1
    Action = 2

class DataExportGui(QWidget):
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
        super(DataExportGui, self).__init__()

        self.drawer = None
        self.topLevelOperator = topLevelOperator

        self.threadRouter = ThreadRouter(self)
        self._thunkEventHandler = ThunkEventHandler(self)
        
        self._initAppletDrawerUic()
        self.initCentralUic()
        self.initViewerControls()
        
        self.parentApplet = parentApplet
        self.guiControlSignal = parentApplet.guiControlSignal
        self.progressSignal = parentApplet.progressSignal
        
        def handleNewDataset( multislot, index ):
            # Make room in the GUI table
            self.batchOutputTableWidget.insertRow( index )
            
            # Update the table row data when this slot has new data
            # We can't bind in the row here because the row may change in the meantime.
            multislot[index].notifyReady( bind( self.updateTableForSlot ) )
            if multislot[index].ready():
                self.updateTableForSlot( multislot[index] )

            multislot[index].notifyUnready( self._updateExportButtons )
            multislot[index].notifyReady( self._updateExportButtons )

        self.topLevelOperator.ExportPath.notifyInserted( bind( handleNewDataset ) )
        
        # For each dataset that already exists, update the GUI
        for i, subslot in enumerate(self.topLevelOperator.ExportPath):
            handleNewDataset( self.topLevelOperator.ExportPath, i )
            if subslot.ready():
                self.updateTableForSlot(subslot)
    
        def handleImageRemoved( multislot, index, finalLength ):
            if self.batchOutputTableWidget.rowCount() <= finalLength:
                return

            # Remove the row we don't need any more
            self.batchOutputTableWidget.removeRow( index )

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
        drawerPath = os.path.join( localDir, "dataExportDrawer.ui")
        self.drawer = uic.loadUi(drawerPath)

        self.drawer.settingsButton.clicked.connect( self._chooseSettings )
        self.drawer.exportAllButton.clicked.connect( self.exportAllResults )
        self.drawer.exportAllButton.setIcon( QIcon(ilastikIcons.Save) )
        self.drawer.deleteAllButton.clicked.connect( self.deleteAllResults )
        self.drawer.deleteAllButton.setIcon( QIcon(ilastikIcons.Clear) )

    def initCentralUic(self):
        """
        Load the GUI from the ui file into this class and connect it with event handlers.
        """
        # Load the ui file into this class (find it in our own directory)
        localDir = os.path.split(__file__)[0]
        uic.loadUi(localDir+"/dataExport.ui", self)

        self.batchOutputTableWidget.resizeRowsToContents()
        self.batchOutputTableWidget.resizeColumnsToContents()
        self.batchOutputTableWidget.setAlternatingRowColors(True)
        self.batchOutputTableWidget.setShowGrid(False)
        self.batchOutputTableWidget.horizontalHeader().setResizeMode(0, QHeaderView.Interactive)
        
        self.batchOutputTableWidget.horizontalHeader().resizeSection(Column.Dataset, 200)
        self.batchOutputTableWidget.horizontalHeader().resizeSection(Column.ExportLocation, 250)
        self.batchOutputTableWidget.horizontalHeader().resizeSection(Column.Action, 100)

        self.batchOutputTableWidget.verticalHeader().hide()

        # Set up handlers
        self.batchOutputTableWidget.itemSelectionChanged.connect(self.handleTableSelectionChange)

        # Set up the viewer area
        self.initViewerStack()
        self.splitter.setSizes([150, 850])
    
    def initViewerStack(self):
        self.layerViewerGuis = {}
        self.viewerStack.addWidget( QWidget() )
        
    def initViewerControls(self):
        self._viewerControlWidgetStack = QStackedWidget(parent=self)

    def _chooseSettings(self):
        opExportModelOp, opSubRegion = get_model_op( self.topLevelOperator )
        if opExportModelOp is None:
            QMessageBox.information( self, 
                                     "Image not ready for export", 
                                     "Export isn't possible yet: No images are ready for export.  "
                                     "Please configure upstream pipeline with valid settings and try again." )
            return
        
        settingsDlg = DataExportOptionsDlg(self, opExportModelOp)
        if settingsDlg.exec_() == DataExportOptionsDlg.Accepted:
            # Copy the settings from our 'model op' into the real op
            setting_slots = [ opExportModelOp.RegionStart,
                              opExportModelOp.RegionStop,
                              opExportModelOp.InputMin,
                              opExportModelOp.InputMax,
                              opExportModelOp.ExportMin,
                              opExportModelOp.ExportMax,
                              opExportModelOp.ExportDtype,
                              opExportModelOp.OutputAxisOrder,
                              opExportModelOp.OutputFilenameFormat,
                              opExportModelOp.OutputInternalPath,
                              opExportModelOp.OutputFormat ]

            # Disconnect the special 'transaction' slot to prevent these 
            #  settings from triggering many calls to setupOutputs.
            self.topLevelOperator.TransactionSlot.disconnect()

            for model_slot in setting_slots:
                real_inslot = getattr(self.topLevelOperator, model_slot.name)
                if model_slot.ready():
                    real_inslot.setValue( model_slot.value )
                else:
                    real_inslot.disconnect()

            # Re-connect the 'transaction' slot to apply all settings at once.
            self.topLevelOperator.TransactionSlot.setValue(True)

            # Discard the temporary model op
            opExportModelOp.cleanUp()
            opSubRegion.cleanUp()

            print "configured shape is: {}".format( self.topLevelOperator.getLane(0).ImageToExport.meta.shape )

            # Update the gui with the new export paths            
            for index, slot in enumerate(self.topLevelOperator.ExportPath):
                self.updateTableForSlot(slot)

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
                
        self.batchOutputTableWidget.setItem( row, Column.Dataset, QTableWidgetItem(nickname) )
        self.batchOutputTableWidget.setItem( row, Column.ExportLocation, QTableWidgetItem( exportPath ) )

        exportNowButton = QPushButton("Export")
        exportNowButton.setToolTip("Generate individual batch output dataset.")
        exportNowButton.clicked.connect( bind(self.exportResultsForSlot, self.topLevelOperator[row] ) )
        self.batchOutputTableWidget.setCellWidget( row, Column.Action, exportNowButton )

        # Select a row if there isn't one already selected.
        selectedRanges = self.batchOutputTableWidget.selectedRanges()
        if len(selectedRanges) == 0:
            self.batchOutputTableWidget.selectRow(0)

    def _updateExportButtons(self, *args):
        """Called when at least one dataset became 'unready', so we have to disable the export button."""
        all_ready = True
        # Enable/disable the appropriate export buttons in the table.
        # Use ThunkEvents to ensure that this happens in the Gui thread.
        for row, slot in enumerate( self.topLevelOperator.ImageToExport ):
            all_ready &= slot.ready()
            export_button = self.batchOutputTableWidget.cellWidget( row, Column.Action )
            if export_button is not None:
                executable_event = ThunkEvent( partial(export_button.setEnabled, slot.ready()) )
                QApplication.instance().postEvent( self, executable_event )

        # Disable the "Export all" button unless all slots are ready.
        executable_event = ThunkEvent( partial(self.drawer.exportAllButton.setEnabled, all_ready) )
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
        selectedRanges = self.batchOutputTableWidget.selectedRanges()
        for rng in selectedRanges:
            for row in range(rng.topRow(), rng.bottomRow()+1):
                selectedItemRows.add(row)
        
        # Disconnect from selection change notifications while we do this
        self.batchOutputTableWidget.itemSelectionChanged.disconnect(self.handleTableSelectionChange)
        for row in selectedItemRows:
            self.batchOutputTableWidget.selectRow(row)

        # Reconnect now that we're finished
        self.batchOutputTableWidget.itemSelectionChanged.connect(self.handleTableSelectionChange)
        
    def exportSlots(self, laneViewList ):
        try:
            # Don't let anyone change the classifier while we're exporting...
            self.guiControlSignal.emit( ilastik.applets.base.applet.ControlCommand.DisableUpstream )
            
            # Also disable this applet's controls
            self.guiControlSignal.emit( ilastik.applets.base.applet.ControlCommand.DisableSelf )

            # Start with 1% so the progress bar shows up
            self.progressSignal.emit(0)
            self.progressSignal.emit(1)

            def signalFileProgress(slotIndex, percent):
                self.progressSignal.emit( (100*slotIndex + percent) / len(laneViewList) ) 

            for i, opLaneView in enumerate(laneViewList):
                logger.debug("Exporting result {}".format(i))

                # If the operator provides a progress signal, use it.
                slotProgressSignal = opLaneView.progressSignal
                slotProgressSignal.subscribe( partial(signalFileProgress, i) )

                try:
                    opLaneView.run_export()
                except Exception as ex:
                    msg = "Failed to generate export file: \n"
                    msg += opLaneView.ExportPath.value
                    msg += "\n{}".format( ex )
                    self.showExportError(msg)
                    
                    logger.error( msg )
                    import traceback
                    traceback.print_exc()

                # We're finished with this file. 
                self.progressSignal.emit( 100*(i+1)/float(len(laneViewList)) )
                
            # Ensure the shell knows we're really done.
            self.progressSignal.emit(100)
        except:
            # Cancel our progress.
            self.progressSignal.emit(0, True)
            raise
        finally:            
            # Now that we're finished, it's okay to use the other applets again.
            self.guiControlSignal.emit( ilastik.applets.base.applet.ControlCommand.Pop ) # Enable ourselves
            self.guiControlSignal.emit( ilastik.applets.base.applet.ControlCommand.Pop ) # Enable the others we disabled

    @threadRouted
    def showExportError(self, msg):
        QMessageBox.critical(self, msg, "Failed to export", msg )

    def exportResultsForSlot(self, opLane):
        # Do this in a separate thread so the UI remains responsive
        exportThread = threading.Thread(target=bind(self.exportSlots, [opLane]), name="BatchIOExportThread")
        exportThread.start()
    
    def exportAllResults(self):
        # Do this in a separate thread so the UI remains responsive
        exportThread = threading.Thread(target=bind(self.exportSlots, self.topLevelOperator), name="BatchIOExportThread")
        exportThread.start()

    def deleteAllResults(self):
        for innerOp in self.topLevelOperator:
            operatorView = innerOp
            operatorView.cleanupOnDiskView()
            pathComp = PathComponents(operatorView.ExportPath.value, operatorView.WorkingDirectory.value)
            if os.path.exists(pathComp.externalPath):
                os.remove(pathComp.externalPath)
            operatorView.setupOnDiskView()
            # we need to toggle the dirts state in order to enforce a frech dirty signal
            operatorView.Dirty.setValue( False )
            operatorView.Dirty.setValue( True )

    def showSelectedDataset(self):
        """
        Show the exported file in the viewer
        """
        # Get the selected row and corresponding slot value
        selectedRanges = self.batchOutputTableWidget.selectedRanges()
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
        return DataExportLayerViewerGui(opLane)

class DataExportLayerViewerGui(LayerViewerGui):
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
            
            








