# Standard
import re
import traceback
import os
import time
from functools import partial
import weakref
import logging

# SciPy
import numpy
import platform
import threading

# PyQt
from PyQt4 import uic
from PyQt4.QtCore import pyqtSignal, QObject, Qt, QSize, QStringList, QTimer
from PyQt4.QtGui import QMainWindow, QWidget, QMenu, QApplication,\
                        QStackedWidget, qApp, QFileDialog, QKeySequence, QMessageBox, \
                        QTreeWidgetItem, QAbstractItemView, QProgressBar, QDialog, \
                        QInputDialog, QIcon, QFont, QToolButton, QLabel, QTreeWidget, \
                        QVBoxLayout, QHBoxLayout, QShortcut

# lazyflow
from lazyflow.roi import TinyVector
from lazyflow.graph import Operator
import lazyflow.tools.schematic
from lazyflow.operators.arrayCacheMemoryMgr import ArrayCacheMemoryMgr, MemInfoNode

# volumina
from volumina.utility import PreferencesManager, ShortcutManagerDlg, ShortcutManager

# ilastik
from ilastik.workflow import getAvailableWorkflows, getWorkflowFromName
from ilastik.utility import bind
from ilastik.utility.gui import ThunkEventHandler, ThreadRouter, threadRouted
from ilastik.applets.base.applet import Applet, ControlCommand, ShellRequest
from ilastik.applets.base.appletGuiInterface import AppletGuiInterface
from ilastik.shell.projectManager import ProjectManager
from ilastik.utility.gui.eventRecorder import EventRecorderGui
from ilastik.config import cfg as ilastik_config
from iconMgr import ilastikIcons
from ilastik.utility.pathHelpers import compressPathForDisplay
from ilastik.shell.gui.errorMessageFilter import ErrorMessageFilter
from ilastik.shell.gui.memUsageDialog import MemUsageDialog
from ilastik.shell.shellAbc import ShellABC

# Import all known workflows now to make sure they are all registered with getWorkflowFromName()
import ilastik.workflows

ILASTIKFont = QFont("Helvetica",10,QFont.Bold)

logger = logging.getLogger(__name__)

#===----------------------------------------------------------------------------------------------------------------===
#=== ShellActions                                                                                                   ===
#===----------------------------------------------------------------------------------------------------------------===

class ShellActions(object):
    """
    The shell provides the applet constructors with access to his GUI actions.
    They are provided in this class.
    """
    def __init__(self):
        self.openProjectAction = None
        self.saveProjectAction = None
        self.saveProjectAsAction = None
        self.saveProjectSnapshotAction = None
        self.importProjectAction = None
        self.quitAction = None
 
#===----------------------------------------------------------------------------------------------------------------===
#=== MemoryWidget                                                                                                   ===
#===----------------------------------------------------------------------------------------------------------------===

class MemoryWidget(QWidget):
    """Displays the current memory consumption and a button to open
       a detailed memory consumption / usage dialog.
    """
    def __init__(self, parent=None):
        super(MemoryWidget, self).__init__(parent)
        self.label = QLabel()
        h = QHBoxLayout() 
        h.setContentsMargins(0,0,0,0)
        w = QWidget()
        h.addWidget(self.label)
        self.showDialogButton = QToolButton()
        self.showDialogButton.setText("...")
        h.addWidget(self.showDialogButton)
        self.cleanUp()
        self.setLayout(h)
    def cleanUp(self):
        self.setMemoryBytes(0)
    def setMemoryBytes(self, bytes):
        self.label.setText("cached: %1.1f MB" % (bytes/(1024.0**2.0)))
 
#===----------------------------------------------------------------------------------------------------------------===
#=== ProgressDisplayManager                                                                                         ===
#===----------------------------------------------------------------------------------------------------------------===

class ProgressDisplayManager(QObject):
    """
    Manages progress signals from applets and displays them in the status bar.
    """
    # Instead of connecting to applet progress signals directly,
    # we forward them through this qt signal.
    # This way we get the benefits of a queued connection without 
    #  requiring the applet interface to be dependent on qt.
    dispatchSignal = pyqtSignal(int, int, "bool")
    
    def __init__(self, statusBar):
        """
        """
        super(ProgressDisplayManager, self).__init__( parent=statusBar.parent() )
        self.statusBar = statusBar
        self.appletPercentages = {} # applet_index : percent_progress
        self.workflow = None
        
        self.progressBar = QProgressBar()
        self.statusBar.addWidget(self.progressBar)
        self.progressBar.setHidden(True)
       
        self.memoryWidget = MemoryWidget()
        self.memoryWidget.showDialogButton.clicked.connect(self.parent().showMemUsageDialog)
        self.statusBar.addPermanentWidget(self.memoryWidget)
        
        mgr = ArrayCacheMemoryMgr.instance
        def printIt(msg):
            self.memoryWidget.setMemoryBytes(msg) 
        mgr.totalCacheMemory.subscribe(printIt)
        
        # Route all signals we get through a queued connection, to ensure that they are handled in the GUI thread        
        self.dispatchSignal.connect(self.handleAppletProgressImpl)

        # Add all applets from the workflow
    
    def initializeForWorkflow(self, workflow):
        """When a workflow is available, call this method to connect the workflows' progress signals
        """
        for index, app in enumerate(workflow.applets):
            self._addApplet(index, app)
    
    def cleanUp(self):
        # Disconnect everything
        if self.workflow is not None:
            for index, app in enumerate(self.workflow.applets):
                self._removeApplet(index, app)
        self.memoryWidget.cleanUp()
        self.progressBar.hide()
    
    def _removeApplet(self, index, app):
        app.progressSignal.disconnectAll()
        for serializer in app.dataSerializers:
            serializer.progressSignal.disconnectAll()
    
    def _addApplet(self, index, app):
        # Subscribe to progress updates from this applet,
        # and include the applet index in the signal parameters.
        app.progressSignal.connect( bind(self.handleAppletProgress, index) )
        
        # Also subscribe to this applet's serializer progress updates.
        # (Progress will always come from either the serializer or the applet itself; not both at once.)
        for serializer in app.dataSerializers:
            serializer.progressSignal.connect( bind( self.handleAppletProgress, index ) )

    def handleAppletProgress(self, index, percentage, cancelled=False):
        # Forward the signal to the handler via our qt signal, which provides a queued connection.
        self.dispatchSignal.emit( index, percentage, cancelled )

    def handleAppletProgressImpl(self, index, percentage, cancelled):
        # No need for locking; this function is always run from the GUI thread
        if cancelled:
            if index in self.appletPercentages.keys():
                del self.appletPercentages[index]
        else:
            # Take max (never go back down)
            if index in self.appletPercentages:
                oldPercentage = self.appletPercentages[index]
                self.appletPercentages[index] = max(percentage, oldPercentage)
            # First percentage we get MUST be 0 or -1.
            # Other notifications are ignored.
            if index in self.appletPercentages or percentage == 0 or percentage == -1:
                self.appletPercentages[index] = percentage

        numActive = len(self.appletPercentages)
        if numActive > 0:
            totalPercentage = numpy.sum(self.appletPercentages.values()) / numActive
        
        # If any applet gave -1, put progress bar in "busy indicator" mode
        if (TinyVector(self.appletPercentages.values()) == -1).any():
            self.progressBar.setMaximum(0)
        else:
            self.progressBar.setMaximum(100)
    
        if numActive == 0 or totalPercentage == 100:
            self.progressBar.setHidden(True)
            self.appletPercentages.clear()
        else:
            self.progressBar.setHidden(False)
            self.progressBar.setValue(totalPercentage)

#===----------------------------------------------------------------------------------------------------------------===
#=== IlastikShell                                                                                                   ===
#===----------------------------------------------------------------------------------------------------------------===

class IlastikShell( QMainWindow ):
    """
    The GUI's main window.  Simply a standard 'container' GUI for one or more applets.
    """

    def __init__( self, parent = None, new_workflow_cmdline_args=None, flags = Qt.WindowFlags(0) ):
        QMainWindow.__init__(self, parent = parent, flags = flags)
        # Register for thunk events (easy UI calls from non-GUI threads)
        self.thunkEventHandler = ThunkEventHandler(self)

        self._new_workflow_cmdline_args = new_workflow_cmdline_args
        
        self.projectManager = None
        self.projectDisplayManager = None
        
        self._loaduifile()
        
        self.progressDisplayManager = ProgressDisplayManager(self.statusBar)
        
        #self.appletBar.setExpandsOnDoubleClick(False) #bug 193.
        #self.appletBar.setSelectionMode(QAbstractItemView.NoSelection)
        
        self._memDlg = None #this will hold the memory usage dialog once created
        
        self.imageSelectionGroup.setHidden(True)

        self.setAttribute(Qt.WA_AlwaysShowToolTips)
        
        if ilastik_config.getboolean("ilastik", "debug") or 'Ubuntu' in platform.platform():
            # Native menus are prettier, but aren't working on Ubuntu at this time (Qt 4.7, Ubuntu 11)
            # Navive menus also required for event-recorded tests
            self.menuBar().setNativeMenuBar(False)
            
        (self._projectMenu, self._shellActions) = self._createProjectMenu()
        self._settingsMenu = self._createSettingsMenu()
        if ilastik_config.getboolean("ilastik", "debug"):
            self._debugMenu = self._createDebugMenu()
        self._helpMenu = self._createHelpMenu()
        self.menuBar().addMenu( self._projectMenu  )
        self.menuBar().addMenu( self._settingsMenu )
        if ilastik_config.getboolean("ilastik", "debug"):
            self.menuBar().addMenu( self._debugMenu )
        self.menuBar().addMenu( self._helpMenu    )
        
        assert self.thread() == QApplication.instance().thread()
        assert self.menuBar().thread() == self.thread()
        assert self._projectMenu.thread() == self.thread()
        assert self._settingsMenu.thread() == self.thread()
        
        self.appletBar.currentChanged.connect(self.handleAppletBarItemExpanded)
        #self.appletBar.clicked.connect(self.handleAppletBarClick)
        #self.appletBar.setVerticalScrollMode( QAbstractItemView.ScrollPerPixel )
        
        self.currentAppletIndex = 0

        self.currentImageIndex = -1
        self.populatingImageSelectionCombo = False
        self.imageSelectionCombo.currentIndexChanged.connect( self.changeCurrentInputImageIndex )
        
        self.enableWorkflow = False # Global mask applied to all applets
        self._controlCmds = []      # Track the control commands that have been issued by each applet so they can be popped.
        self._disableCounts = []    # Controls for each applet can be disabled by his peers.
                                    # No applet can be enabled unless his disableCount == 0

        self._refreshDrawerRecursionGuard = False

        self.setupOpenFileButtons()
        self.updateShellProjectDisplay()
        
        self.threadRouter = ThreadRouter(self) # Enable @threadRouted
        self._recorderGui = EventRecorderGui()
        
        self.errorMessageFilter = ErrorMessageFilter(self)
        
        windowSize = PreferencesManager().get("shell","startscreenSize")
        if windowSize is not None:
            self.resize(*windowSize)
            
        self._initShortcuts()
        
    def _initShortcuts(self):
        mgr = ShortcutManager()
        shortcutGroupName = "Ilastik Shell"

        nextImage = QShortcut( QKeySequence("PgDown"), self, member=self._nextImage)
        mgr.register( shortcutGroupName,
                      "Switch to next image",
                      nextImage)        

        prevImage = QShortcut( QKeySequence("PgUp"), self, member=self._prevImage)
        mgr.register( shortcutGroupName,
                      "Switch to previous image",
                      prevImage)   
    
    def _nextImage(self):
        newIndex = min(self.imageSelectionCombo.count()-1,self.imageSelectionCombo.currentIndex()+1)
        self.imageSelectionCombo.setCurrentIndex(newIndex)
    
    def _prevImage(self):
        newIndex = max(0,self.imageSelectionCombo.currentIndex()-1)
        self.imageSelectionCombo.setCurrentIndex(newIndex)
        
    @property
    def _applets(self):
        if self.projectManager is None:
            return []
        else:
            return self.projectManager.workflow.applets
    
    @property
    def workflow(self):
        return self.projectManager and self.projectManager.workflow
    
    def loadWorkflow(self, workflow_class):
        self.onNewProjectActionTriggered(workflow_class)
    
    def getWorkflow(self,w = None):
        
        listOfItems = [workflowName for _,workflowName in getAvailableWorkflows()]
        if w is not None and w in listOfItems:
            cur = listOfItems.index(w)
        else:
            cur = 0
        
        res,ok = QInputDialog.getItem(self,
                        "Workflow Selection",
                        "Select a workflow which should open the file.",
                        listOfItems,
                        cur,
                        False)
        
        if ok:
            return getWorkflowFromName(str(res))
    
    def _createProjectMenu(self):
        # Create a menu for "General" (non-applet) actions
        menu = QMenu("&Project", self)
        menu.setObjectName("project_menu")

        shellActions = ShellActions()

        # Menu item: New Project
        newProjectMenu = menu.addMenu("&New Project...")
        
        workflowActions = []
        for w,_name in getAvailableWorkflows():
            a = newProjectMenu.addAction(_name)
            a.triggered.connect(partial(self.onNewProjectActionTriggered,w))
        
        # Menu item: Open Project 
        shellActions.openProjectAction = menu.addAction("&Open Project...")
        shellActions.openProjectAction.setShortcuts( QKeySequence.Open )
        shellActions.openProjectAction.triggered.connect(self.onOpenProjectActionTriggered)
        
        # Menu item: Save Project
        shellActions.saveProjectAction = menu.addAction("&Save Project")
        shellActions.saveProjectAction.setShortcuts( QKeySequence.Save )
        shellActions.saveProjectAction.triggered.connect(self.onSaveProjectActionTriggered)

        # Menu item: Save Project As
        shellActions.saveProjectAsAction = menu.addAction("&Save Project As...")
        shellActions.saveProjectAsAction.setShortcuts( QKeySequence.SaveAs )
        shellActions.saveProjectAsAction.triggered.connect(self.onSaveProjectAsActionTriggered)

        # Menu item: Save Project Snapshot
        shellActions.saveProjectSnapshotAction = menu.addAction("&Save Copy as...")
        shellActions.saveProjectSnapshotAction.triggered.connect(self.onSaveProjectSnapshotActionTriggered)
        
        # Menu item: Import Project
        shellActions.importProjectAction = menu.addAction("&Import Project...")
        shellActions.importProjectAction.triggered.connect(self.onImportProjectActionTriggered)
        
        shellActions.closeAction = menu.addAction("&Close")
        shellActions.closeAction.setShortcuts( QKeySequence.Close )
        shellActions.closeAction.triggered.connect(self.onCloseActionTriggered)
        
        # Menu item: Quit
        shellActions.quitAction = menu.addAction("&Quit")
        shellActions.quitAction.setShortcuts( QKeySequence.Quit )
        shellActions.quitAction.triggered.connect(self.onQuitActionTriggered)
        shellActions.quitAction.setShortcut( QKeySequence.Quit )
        
        return (menu, shellActions)
    
    def setupOpenFileButtons(self):
        
        for b in self.openFileButtons:
            b.close()
            b.deleteLater()
        self.openFileButtons = []
        
        projects = PreferencesManager().get("shell","recently opened list")
        
        if projects is not None:
            for path,workflow in projects[::-1]:
                if not os.path.exists(path):
                    continue
                b = QToolButton(self.startscreen)
                b.setAutoRaise(True)
                b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
                b.setIcon( QIcon(ilastikIcons.Open) )
                b.setFont(ILASTIKFont)
                
                #parse path
                b.setToolTip(path)
                compressedpath = compressPathForDisplay(path,50)
                if len(workflow)>30:
                    compressedworkflow = workflow[:27]+"..."
                else:
                    compressedworkflow = workflow
                text = "{0} ({1})".format(compressedpath,compressedworkflow)
                b.setText(text)
                b.clicked.connect(partial(self.openFileAndCloseStartscreen,path))
                self.startscreen.VL2.insertWidget(3,b,2)
                self.openFileButtons.append(b)
    
    def _loaduifile(self):
        localDir = os.path.split(__file__)[0]
        if localDir == "":localDir = os.getcwd()
        
        self.startscreen = uic.loadUi( localDir + "/ui/ilastikShell.ui", self )
        
        self.startscreen.CreateList.setWidget(self.startscreen.VL1.widget())
        self.startscreen.CreateList.setWidgetResizable(True)
        self.startscreen.OpenList.setWidget(self.startscreen.VL2.widget())
        self.startscreen.OpenList.setWidgetResizable(True)
        
        self.startscreen.label1.setFont(ILASTIKFont)
        self.startscreen.label2.setFont(ILASTIKFont)
        
        self.openFileButtons = []
        otherButtons = []
        
        self.startscreen.browseFilesButton.setAutoRaise(True)
        self.startscreen.browseFilesButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.startscreen.browseFilesButton.setIcon( QIcon(ilastikIcons.OpenFolder) )
        self.startscreen.browseFilesButton.setFont(ILASTIKFont)
        self.startscreen.browseFilesButton.clicked.connect(self.onOpenProjectActionTriggered)
        otherButtons.append(self.startscreen.browseFilesButton)
        
        for workflow,_name in getAvailableWorkflows():
            b = QToolButton(self.startscreen)
            #b.setDescription(workflow)
            b.setAutoRaise(True)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.clicked.connect(partial(self.loadWorkflow,workflow))
            b.setIcon( QIcon(ilastikIcons.GoNext) )
            b.setText(_name)
            b.setFont(ILASTIKFont)
            self.startscreen.VL1.addWidget(b)
            otherButtons.append(b)
        
        m = max(b.sizeHint().width() for b in self.openFileButtons+otherButtons)
        for b in self.openFileButtons+otherButtons:
            b.setFixedSize(QSize(m,20))
    
    def openFileAndCloseStartscreen(self,path):
        #self.startscreen.setParent(None)
        #del self.startscreen
        self.openProjectFile(path)
    
    def _createHelpMenu(self):
        menu = QMenu("&Help", self)
        menu.setObjectName("help_menu")
        aboutIlastikAction = menu.addAction("&About ilastik")
        aboutIlastikAction.triggered.connect(self._showAboutDialog)
        return menu
    
    def _showAboutDialog(self):
        localDir = os.path.split(__file__)[0]
        dlg = QDialog()
        uic.loadUi( localDir + "/ui/ilastikAbout.ui", dlg)
        dlg.exec_() 
        
    def _createDebugMenu(self):
        menu = QMenu("&Debug", self)
        menu.setObjectName("debug_menu")
        
        detail_levels = [ ('Lowest', 0), ('Some', 1), ('More', 2), ('Even More', 3), ('Unlimited', 100) ]
        exportDebugSubmenu = menu.addMenu("Export Operator Diagram")
        exportWorkflowSubmenu = menu.addMenu("Export Workflow Diagram")
        for name, level in detail_levels:
            exportDebugSubmenu.addAction(name).triggered.connect( partial(self.exportCurrentOperatorDiagram, level) )
            exportWorkflowSubmenu.addAction(name).triggered.connect( partial(self.exportWorkflowDiagram, level) )
    
        menu.addAction( "Open Recorder Controls" ).triggered.connect( self._openRecorderControls )
       
        menu.addAction("&Memory usage").triggered.connect(self.showMemUsageDialog)
        return menu
    
    def showMemUsageDialog(self):
        if self._memDlg is None:
            self._memDlg = MemUsageDialog()
            self._memDlg.setWindowTitle("Memory Usage")
            self._memDlg.showMaximized()
        else:
            self._memDlg.show()
            self._memDlg.raise_()
    
    def _createSettingsMenu(self):
        menu = QMenu("&Settings", self)
        menu.setObjectName("settings_menu")
        # Menu item: Keyboard Shortcuts

        def editShortcuts():
            mgrDlg = ShortcutManagerDlg(self)
        menu.addAction("&Keyboard Shortcuts").triggered.connect(editShortcuts)

        return menu

    def exportCurrentOperatorDiagram(self, detail):        
        op = self._applets[self.currentAppletIndex].topLevelOperator
        assert isinstance(op, Operator), "Top-level operator of your applet must be a lazyflow.Operator if you want to export it!"
        self.exportOperatorDiagram(op, detail)
        
    def exportWorkflowDiagram(self, detail):
        assert isinstance(self.projectManager.workflow, Operator), "Workflow must be an operator if you want to export it!"
        self.exportOperatorDiagram(self.projectManager.workflow, detail)
    
    def exportOperatorDiagram(self, op, detail):
        recentPath = PreferencesManager().get( 'shell', 'recent debug diagram' )
        if recentPath is None:
            defaultPath = os.path.join(os.path.expanduser('~'), op.name + '.svg')
        else:
            defaultPath = os.path.join(os.path.split(recentPath)[0], op.name + '.svg')
        
        svgPath = QFileDialog.getSaveFileName(
           self, "Save operator diagram", defaultPath, "Inkscape Files (*.svg)",
           options=QFileDialog.Options(QFileDialog.DontUseNativeDialog))

        if not svgPath.isNull():
            PreferencesManager().set( 'shell', 'recent debug diagram', str(svgPath) )
            lazyflow.tools.schematic.generateSvgFileForOperator(svgPath, op, detail)

    def _openRecorderControls(self):
        self._recorderGui.show()
    
    def show(self):
        """
        Show the window, and enable/disable controls depending on whether or not a project file present.
        """
        super(IlastikShell, self).show()
        self.enableWorkflow = (self.projectManager is not None)
        self.updateAppletControlStates()
        self.updateShellProjectDisplay()
        # Default to a 50-50 split
        totalSplitterHeight = sum(self.sideSplitter.sizes())
        self.sideSplitter.setSizes([totalSplitterHeight/2, totalSplitterHeight/2])

    def updateShellProjectDisplay(self):
        """
        Update the title bar and allowable shell actions based on the state of the currently loaded project.
        """
        windowTitle = "ilastik - "
        if self.projectManager is None:
            windowTitle += "No Project Loaded"
        else:
            windowTitle += self.projectManager.currentProjectPath
            windowTitle += " - " + self.projectManager.workflow.workflowName
            
            readOnly = self.projectManager.currentProjectIsReadOnly
            if readOnly:
                windowTitle += " [Read Only]"
            
        self.setWindowTitle(windowTitle)        

        # Enable/Disable menu items
        projectIsOpen = self.projectManager is not None
        self._shellActions.saveProjectAction.setEnabled(projectIsOpen and not readOnly) # Can't save a read-only project
        self._shellActions.saveProjectAsAction.setEnabled(projectIsOpen)
        self._shellActions.saveProjectSnapshotAction.setEnabled(projectIsOpen)
        self._shellActions.closeAction.setEnabled(projectIsOpen)

    def setImageNameListSlot(self, multiSlot):
        assert multiSlot.level == 1
        self.imageNamesSlot = multiSlot
        self.cleanupFunctions = []
        
        insertedCallback = bind(self.handleImageNameSlotInsertion)
        self.cleanupFunctions.append( partial( multiSlot.unregisterInserted, insertedCallback ) )
        multiSlot.notifyInserted( insertedCallback )

        removeCallback = bind(self.handleImageNameSlotRemoval)
        self.cleanupFunctions.append( partial( multiSlot.unregisterRemove, removeCallback ) )
        multiSlot.notifyRemove( bind(self.handleImageNameSlotRemoval) )
        
        # Update for the slots that already exist
        for index, slot in enumerate(multiSlot):
            self.handleImageNameSlotInsertion(multiSlot, index)
            self.insertImageName(index, slot)

    @threadRouted
    def insertImageName(self, index, slot ):
        assert threading.current_thread().name == "MainThread"
        if slot.ready():
            self.imageSelectionCombo.setItemText( index, slot.value )
            if self.currentImageIndex == -1:
                self.changeCurrentInputImageIndex(index)
 
    @threadRouted
    def handleImageNameSlotInsertion(self, multislot, index):
        assert threading.current_thread().name == "MainThread"
        assert multislot == self.imageNamesSlot
        self.populatingImageSelectionCombo = True
        self.imageSelectionCombo.insertItem(index, "uninitialized")
        self.populatingImageSelectionCombo = False
        multislot[index].notifyDirty( bind( self.insertImageName, index) )

    @threadRouted
    def handleImageNameSlotRemoval(self, multislot, index):
        assert threading.current_thread().name == "MainThread"
        # Simply remove the combo entry, which causes the currentIndexChanged signal to fire if necessary.
        self.imageSelectionCombo.removeItem(index)
        if len(multislot) == 0:
            self.changeCurrentInputImageIndex(-1)

    def changeCurrentInputImageIndex(self, newImageIndex):
        if newImageIndex != self.currentImageIndex \
        and self.populatingImageSelectionCombo == False:
            if newImageIndex != -1:
                try:
                    # Accessing the image name value will throw if it isn't properly initialized
                    self.imageNamesSlot[newImageIndex].value
                except:
                    # Revert to the original image index.
                    if self.currentImageIndex != -1:
                        assert threading.current_thread().name == "MainThread"
                        self.imageSelectionCombo.setCurrentIndex(self.currentImageIndex)
                    return

            # Alert each central widget and viewer control widget that the image selection changed
            for i in range( len(self._applets) ):
                if newImageIndex == -1:
                    self._applets[i].getMultiLaneGui().setImageIndex(None)
                else:
                    self._applets[i].getMultiLaneGui().setImageIndex(newImageIndex)
                
            self.currentImageIndex = newImageIndex

            if self.currentImageIndex != -1:
                # Force the applet drawer to be redrawn
                self.setSelectedAppletDrawer(self.currentAppletIndex)
            
                # Update all other applet drawer titles
                for applet_index, app in enumerate(self._applets):
                    updatedDrawerTitle = app.name
                    self.appletBar.setItemText( applet_index, updatedDrawerTitle )

    def handleAppletBarItemExpanded(self, modelIndex):
        """
        The user wants to view a different applet bar item.
        """
        drawerIndex = modelIndex
        if drawerIndex != -1:
            self.setSelectedAppletDrawer(drawerIndex)
    
    def setSelectedAppletDrawer(self, applet_index):
        """
        Show the correct applet central widget, viewer control widget, and applet drawer widget for this drawer index.
        """
        if self._refreshDrawerRecursionGuard is False:
            assert threading.current_thread().name == "MainThread"
            self._refreshDrawerRecursionGuard = True
            self.currentAppletIndex = applet_index
            # Collapse all drawers in the applet bar...
            # ...except for the newly selected item.
            drawerModelIndex = self.getModelIndexFromDrawerIndex(applet_index)
            #self.appletBar.expand( drawerModelIndex )
            self.appletBar.setCurrentIndex( drawerModelIndex )
            
            # Select the appropriate central widget, menu widget, and viewer control widget for this applet
            self.showCentralWidget(applet_index)
            self.showViewerControlWidget(applet_index)
            self.showMenus(applet_index)
            self.refreshAppletDrawer( applet_index )
            
            self._refreshDrawerRecursionGuard = False
            
            applet = self._applets[applet_index]
            # Only show the combo if the applet is lane-aware and there is more than one lane loaded.
            self.imageSelectionGroup.setVisible( applet.syncWithImageIndex and self.imageSelectionCombo.count() > 1 )

    def showCentralWidget(self, applet_index):
        if applet_index < len(self._applets):
            centralWidget = self._applets[applet_index].getMultiLaneGui().centralWidget()
            # Replace the placeholder widget, if possible
            if centralWidget is not None:
                if self.appletStack.indexOf( centralWidget ) == -1:
                    self.appletStack.removeWidget( self.appletStack.widget( applet_index ) )
                    self.appletStack.insertWidget( applet_index, centralWidget )
                    # For test recording purposes, every gui we add MUST have a unique name
                    centralWidget.setObjectName("centralWidget_applet_{}_lane_{}".format(applet_index, self.currentImageIndex))

            self.appletStack.setCurrentIndex(applet_index)

    def showViewerControlWidget(self, applet_index ):
        if applet_index < len(self._applets):
            viewerControlWidget = self._applets[applet_index].getMultiLaneGui().viewerControlWidget()        
            # Replace the placeholder widget, if possible
            if viewerControlWidget is not None:
                if self.viewerControlStack.indexOf( viewerControlWidget ) == -1:
                    self.viewerControlStack.addWidget( viewerControlWidget )
                self.viewerControlStack.setCurrentWidget(viewerControlWidget)
                # For test recording purposes, every gui we add MUST have a unique name
                viewerControlWidget.setObjectName( "viewerControls_applet_{}_lane_{}".format( applet_index, self.currentImageIndex ) )

    def refreshAppletDrawer(self, applet_index):
        if applet_index < len(self._applets) and applet_index < self.appletBar.count():
            updatedDrawerTitle = self._applets[applet_index].name
            updatedDrawerWidget = self._applets[applet_index].getMultiLaneGui().appletDrawer()
            self.appletBar.setItemText( applet_index , updatedDrawerTitle ) 
            appletDrawerStackedWidget = self.appletBar.widget(applet_index)
            if appletDrawerStackedWidget.indexOf(updatedDrawerWidget) == -1:
                appletDrawerStackedWidget.addWidget( updatedDrawerWidget )
                # For test recording purposes, every gui we add MUST have a unique name
                appletDrawerStackedWidget.setObjectName( "appletDrawer_applet_{}_lane_{}".format( applet_index, self.currentImageIndex ) )
            appletDrawerStackedWidget.setCurrentWidget( updatedDrawerWidget )
    
    def onCloseActionTriggered(self):
        if not self.confirmQuit():
            return
        if not self.ensureNoCurrentProject():
            return
        self.closeCurrentProject()
        
        self.setupOpenFileButtons()
        self.mainStackedWidget.setCurrentIndex(0)

    def postErrorMessage(self, caption, text):
        '''Thread-safe function to have the GUI display an error dialog with
           the given caption and text.
        '''
        self.thunkEventHandler.post(self.errorMessageFilter.showErrorMessage, caption, text)
    
    def showMenus(self, applet_index):
        self.menuBar().clear()
        self.menuBar().addMenu(self._projectMenu)
        self.menuBar().addMenu(self._settingsMenu)
        if applet_index < len(self._applets):
            appletMenus = self._applets[applet_index].getMultiLaneGui().menus()
            if appletMenus is not None:
                for m in appletMenus:
                    self.menuBar().addMenu(m)
        if ilastik_config.getboolean("ilastik", "debug"):
            self.menuBar().addMenu(self._debugMenu)
        self.menuBar().addMenu(self._helpMenu)

    def getModelIndexFromDrawerIndex(self, drawerIndex):
        drawerTitleItem = self.appletBar.widget(drawerIndex)
        return self.appletBar.indexOf(drawerTitleItem)
                
    def handleAppletBarClick(self, modelIndex):
        #bug #193
        drawerTitleItem = self.appletBar.widget(modelIndex)
        if drawerTitleItem.isDisabled():
            return
        
        # If the user clicks on a top-level item, automatically expand it.
        if modelIndex.parent() == self.appletBar.rootIndex():
            self.appletBar.expand(modelIndex)
        else:
            self.appletBar.setCurrentIndex( modelIndex.parent() )

    def addApplet( self, applet_index, app ):
        assert isinstance( app, Applet ), "Applets must inherit from Applet base class."
        assert app.base_initialized, "Applets must call Applet.__init__ upon construction."

        assert isinstance( app.getMultiLaneGui(), AppletGuiInterface ), \
            "Applet GUIs must conform to the Applet GUI interface."
                
        # Add placeholder widget, since the applet's central widget may not exist yet.
        self.appletStack.addWidget( QWidget(parent=self) )
        
        # Add a placeholder widget
        self.viewerControlStack.addWidget( QWidget(parent=self) )

        # Add rows to the applet bar model

        # Add all of the applet bar's items to the toolbox widget
        controlName = app.name
        controlGuiWidget = app.getMultiLaneGui().appletDrawer()
        
        stackedWidget = QStackedWidget()
        stackedWidget.addWidget( controlGuiWidget )
        
        self.appletBar.addItem( stackedWidget, controlName )

        # Set up handling of GUI commands from this applet
        app.guiControlSignal.connect( bind(self.handleAppletGuiControlSignal, applet_index) )
        self._disableCounts.append(0)
        self._controlCmds.append( [] )

        # Set up handling of shell requests from this applet
        app.shellRequestSignal.connect( partial(self.handleShellRequest, applet_index) )
        
        return applet_index

    def removeAllAppletWidgets(self):
        for app in self._applets:
            app.shellRequestSignal.disconnectAll()
            app.guiControlSignal.disconnectAll()
            app.progressSignal.disconnectAll()
        
        self._clearStackedWidget(self.appletStack)
        self._clearStackedWidget(self.viewerControlStack)
        
        # Remove all drawers
        for i in reversed(range(self.appletBar.count())):
            self.appletBar.removeItem(i)

    def _clearStackedWidget(self, stackedWidget):
        for i in reversed( range( stackedWidget.count() ) ):
            lastWidget = stackedWidget.widget(i)
            stackedWidget.removeWidget(lastWidget)

    def handleAppletGuiControlSignal(self, applet_index, command):
        """
        Applets fire a signal when they want other applet GUIs to be disabled.
        This function handles the signal.
        Each signal is treated as a command to disable other applets.
        A special command, Pop, undoes the applet's most recent command (i.e. re-enables the applets that were disabled).
        If an applet is disabled twice (e.g. by two different applets), then it won't become enabled again until both commands have been popped.
        """
        
        if command == ControlCommand.Pop:
            command = self._controlCmds[applet_index].pop()
            step = -1 # Since we're popping this command, we'll subtract from the disable counts
        else:
            step = 1
            self._controlCmds[applet_index].append( command ) # Push command onto the stack so we can pop it off when the applet isn't busy any more

        # Increase the disable count for each applet that is affected by this command.
        for index, count in enumerate(self._disableCounts):
            if (command == ControlCommand.DisableAll) \
            or (command == ControlCommand.DisableDownstream and index > applet_index) \
            or (command == ControlCommand.DisableUpstream and index < applet_index) \
            or (command == ControlCommand.DisableSelf and index == applet_index):
                self._disableCounts[index] += step

        # Update the control states in the GUI thread
        self.thunkEventHandler.post( self.updateAppletControlStates )

    def handleShellRequest(self, applet_index, requestAction):
        """
        An applet is asking us to do something.  Handle the request.
        """
        if requestAction == ShellRequest.RequestSave:
            # Call the handler directly to ensure this is a synchronous call (not queued to the GUI thread)
            self.projectManager.saveProject()

    def __len__( self ):
        return self.appletBar.count()

    def __getitem__( self, index ):
        return self._applets[index]
    
    def onNewProjectActionTriggered(self, workflow_class=None):
        logger.debug("New Project action triggered")
        newProjectFilePath = self.getProjectPathToCreate()
        if newProjectFilePath is not None:
            # Make sure the user is finished with the currently open project
            if not self.ensureNoCurrentProject():
                return
            
            self.createAndLoadNewProject(newProjectFilePath, workflow_class)
            
    def createAndLoadNewProject(self, newProjectFilePath, workflow_class, h5_file_kwargs={} ):
        '''Create a new project file for the given workflow and open the workflow in the shell.

        To create an in-memory project file call it as follows (the filename is irrelevant in this case):
        createAndLoadNewProject( "tmp.ilp", MyWorkflowClass, h5_file_kwargs={'driver': 'core', 'backing_store': False})

        :param h5_file_kwargs: Passed directly to h5py.File.__init__() of the project file; all standard params except 'mode' are allowed.
        '''

        newProjectFile = ProjectManager.createBlankProjectFile(newProjectFilePath, workflow_class, self._new_workflow_cmdline_args, h5_file_kwargs)
        self._loadProject(newProjectFile, newProjectFilePath, workflow_class, readOnly=False)

    def getProjectPathToCreate(self, defaultPath=None, caption="Create Ilastik Project"):
        """
        Ask the user where he would like to create a project file.
        """
        if defaultPath is None:
            defaultPath = os.path.expanduser("~/MyProject.ilp")
        
        fileSelected = False
        while not fileSelected:
            options = QFileDialog.Options()
            if ilastik_config.getboolean("ilastik", "debug"):
                options |= QFileDialog.DontUseNativeDialog
                # For testing, it's easier if we don't record the overwrite confirmation
                options |= QFileDialog.DontConfirmOverwrite

            projectFilePath = QFileDialog.getSaveFileName(self, caption, defaultPath, 
                                          "Ilastik project files (*.ilp)", options=options)
            # If the user cancelled, stop now
            if projectFilePath.isEmpty():
                return None
            projectFilePath = str(projectFilePath)
            fileSelected = True
            
            # Add extension if necessary
            fileExtension = os.path.splitext(projectFilePath)[1].lower()
            if fileExtension != '.ilp':
                projectFilePath += ".ilp"
                if os.path.exists(projectFilePath):
                    # Since we changed the file path, we need to re-check if we're overwriting an existing file.
                    message = "A file named '" + projectFilePath + "' already exists in this location.\n"
                    message += "Are you sure you want to overwrite it?"
                    buttons = QMessageBox.Yes | QMessageBox.Cancel
                    response = QMessageBox.warning(self, "Overwrite existing project?", message, buttons, defaultButton=QMessageBox.Cancel)
                    if response == QMessageBox.Cancel:
                        # Try again...
                        fileSelected = False

        return projectFilePath

    def onImportProjectActionTriggered(self):
        """
        Import an existing project into a new file.
        This involves opening the old file, saving it to a new file, and then opening the new file.
        """
        logger.debug("Import Project Action")

        # Find the directory of the most recently *imported* project
        mostRecentImportPath = PreferencesManager().get( 'shell', 'recently imported' )
        if mostRecentImportPath is not None:
            defaultDirectory = os.path.split(mostRecentImportPath)[0]
        else:
            defaultDirectory = os.path.expanduser('~')

        # Select the paths to the ilp to import and the name of the new one we'll create
        importedFilePath = self.getProjectPathToOpen(defaultDirectory)
        if importedFilePath is not None:
            PreferencesManager().set('shell', 'recently imported', importedFilePath)
            defaultFile, ext = os.path.splitext(importedFilePath)
            defaultFile += "_imported"
            defaultFile += ext
            newProjectFilePath = self.getProjectPathToCreate(defaultFile)

        # If the user didn't cancel
        if importedFilePath is not None and newProjectFilePath is not None:
            if not self.ensureNoCurrentProject():
                return
            newProjectFile = ProjectManager.createBlankProjectFile(newProjectFilePath)
            self._loadProject(newProjectFile, newProjectFilePath, workflow_class=None, readOnly=False, importFromPath=importedFilePath)
        
    def getProjectPathToOpen(self, defaultDirectory):
        """
        Return the path of the project the user wants to open (or None if he cancels).
        """
        options = QFileDialog.Options()
        if ilastik_config.getboolean("ilastik", "debug"):
            options = QFileDialog.Options(QFileDialog.DontUseNativeDialog)
        
        projectFilePath = QFileDialog.getOpenFileName(
           self, "Open Ilastik Project", defaultDirectory, "Ilastik project files (*.ilp)", options=options)

        # If the user canceled, stop now        
        if projectFilePath.isNull():
            return None

        return str(projectFilePath)

    def onOpenProjectActionTriggered(self):
        logger.debug("Open Project action triggered")
        
        # Find the directory of the most recently opened project
        mostRecentProjectPath = PreferencesManager().get( 'shell', 'recently opened' )
        if mostRecentProjectPath:
            defaultDirectory = os.path.split(mostRecentProjectPath)[0]
        else:
            defaultDirectory = os.path.expanduser('~')

        projectFilePath = self.getProjectPathToOpen(defaultDirectory)
        if projectFilePath is not None:
            # Make sure the user is finished with the currently open project
            if not self.ensureNoCurrentProject():
                return
            
            self.openProjectFile(projectFilePath)
    
    def openProjectFile(self, projectFilePath):
        try:
            hdf5File, workflow_class, readOnly = ProjectManager.openProjectFile(projectFilePath)
        except ProjectManager.ProjectVersionError,e:
            QMessageBox.warning(self, "Old Project", "Could not load old project file: " + projectFilePath + ".\nPlease try 'Import Project' instead.")
        except ProjectManager.FileMissingError:
            QMessageBox.warning(self, "Missing File", "Could not find project file: " + projectFilePath)
        except:
            logger.error( traceback.format_exc() )
            QMessageBox.warning(self, "Corrupted Project", "Unable to open project file: " + projectFilePath)
        else:            
            #as load project can take a while, show a wait cursor
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.statusBar.showMessage("Loading project %s ..." % projectFilePath)
            self._loadProject(hdf5File, projectFilePath, workflow_class, readOnly)
            QApplication.restoreOverrideCursor()
            self.statusBar.clearMessage()
    
    def _loadProject(self, hdf5File, projectFilePath, workflow_class, readOnly, importFromPath=None):
        """
        Load the data from the given hdf5File (which should already be open).
        Populate the shell with widgets from all the applets in the new workflow.
        """

        if workflow_class is None:
            #ask the user to name a workflow
            workflow_class = self.getWorkflow()

        # If the user cancelled, give up.        
        if workflow_class is None:
            return

        workflow_cmdline_args = None
        if "workflow_cmdline_args" in hdf5File.keys():
            # Use workflow_cmdline_args IF PRESENT
            # To ensure that the workflow is loaded in the same state it was created,
            #  we do not attempt to provide any extra kwargs from the current session.
            workflow_cmdline_args = []
            if len(hdf5File["workflow_cmdline_args"]) > 0:
                workflow_cmdline_args = map(str, hdf5File["workflow_cmdline_args"][...])

        try:
            assert self.projectManager is None, "Expected projectManager to be None."
            self.projectManager = ProjectManager( workflow_class,
                                                  workflow_cmdline_args=workflow_cmdline_args)
            
        except Exception, e:
            traceback.print_exc()
            QMessageBox.warning(self, "Failed to Load", "Could not load project file.\n" + e.message)
        else:
            
            # Add all the applets from the workflow
            for index, app in enumerate(self.projectManager.workflow.applets):
                self.addApplet(index, app)
            
            start = time.time()
            #load the project data from file
            if importFromPath is None:
                #FIXME: load the project asynchronously
                self.projectManager._loadProject(hdf5File, projectFilePath, readOnly)
            else:
                assert not readOnly, "Can't import into a read-only file."
                self.projectManager._importProject(importFromPath, hdf5File, projectFilePath)
                
            stop = time.time()
            print "Loading the project took %f sec." % (stop-start,)
            
            #add file and workflow to users preferences
            mostRecentProjectPaths = PreferencesManager().get('shell', 'recently opened list')
            if mostRecentProjectPaths is None:
                mostRecentProjectPaths = []
            
            workflowName = self.projectManager.workflow.workflowName
            
            for proj,work in mostRecentProjectPaths[:]:
                if proj==projectFilePath and (proj,work) in mostRecentProjectPaths:
                    mostRecentProjectPaths.remove((proj,work))
            
            mostRecentProjectPaths.insert(0,(projectFilePath,workflowName))
            
            #cut list of stored files at randomly chosen number of 5
            if len(mostRecentProjectPaths) > 5:
                mostRecentProjectPaths = mostRecentProjectPaths[:5]
            
            PreferencesManager().set('shell', 'recently opened list', mostRecentProjectPaths)
            PreferencesManager().set('shell', 'recently opened', projectFilePath)
            
            #be friendly to user: if this file has not specified a default workflow, do it now
            if not "workflowName" in hdf5File.keys() and not readOnly:
                hdf5File.create_dataset("workflowName",data = workflowName)
            
            #switch away from the startup screen to show the loaded project
            self.mainStackedWidget.setCurrentIndex(1)
            # By default, make the splitter control expose a reasonable width of the applet bar
            self.mainSplitter.setSizes([300,1])
           
            self.progressDisplayManager.cleanUp()
            self.progressDisplayManager.initializeForWorkflow(self.projectManager.workflow)
                
            self.setImageNameListSlot( self.projectManager.workflow.imageNameListSlot )
            self.updateShellProjectDisplay()

            # Enable all the applet controls
            self.enableWorkflow = True
            self.updateAppletControlStates()

            if "currentApplet" in hdf5File.keys():
                appletName = hdf5File["currentApplet"].value
                self.setSelectedAppletDrawer(appletName)
            else:
                self.setSelectedAppletDrawer(self.projectManager.workflow.defaultAppletIndex)

    def closeCurrentProject(self):
        """
        Undo everything that was done in loadProject()
        """
        assert threading.current_thread().name == "MainThread"
        if self.projectManager is not None:
            
            projectFile = self.projectManager.currentProjectFile 
            if projectFile is not None:
                if "currentApplet" in projectFile.keys():
                    del projectFile["currentApplet"]
                self.projectManager.currentProjectFile.create_dataset("currentApplet",data = self.currentAppletIndex)
            
            self.removeAllAppletWidgets()
            for f in self.cleanupFunctions:
                f()

            self.imageSelectionCombo.clear()
            self.changeCurrentInputImageIndex(-1)

            if self.projectDisplayManager is not None: 
                old = weakref.ref(self.projectDisplayManager)
                self.projectDisplayManager.cleanUp()
                self.projectDisplayManager = None # Destroy display manager
                # Ensure that it was really destroyed
                assert old() is None, "There shouldn't be extraneous references to the project display manager!"

            old = weakref.ref(self.projectManager)
            self.projectManager.cleanUp()
            self.projectManager = None # Destroy project manager
            # Ensure that it was really destroyed
            assert old() is None, "There shouldn't be extraneous references to the project manager!"
        
        self.enableWorkflow = False
        self._controlCmds = []
        self._disableCounts = []
        self.updateAppletControlStates()
        self.updateShellProjectDisplay()
        
    def ensureNoCurrentProject(self, assertClean=False):
        """
        Close the current project.  If it's dirty, we ask the user for confirmation.
        
        The ``assertClean`` parameter is for tests.  Setting it to True will raise an assertion if the project was dirty.
        """
        closeProject = True
        if self.projectManager:
            dirtyApplets = self.projectManager.getDirtyAppletNames()
            if len(dirtyApplets) > 0:
                # Testing assertion
                assert not assertClean, "Expected a clean project but found it to be dirty!"
    
                message = "Your current project is about to be closed, but it has unsaved changes which will be lost.\n"
                message += "Are you sure you want to proceed?\n"
                message += "(Unsaved changes in: {})".format( ', '.join(dirtyApplets) )
                buttons = QMessageBox.Yes | QMessageBox.Cancel
                response = QMessageBox.warning(self, "Discard unsaved changes?", message, buttons, defaultButton=QMessageBox.Cancel)
                closeProject = (response == QMessageBox.Yes)
            

        if closeProject:
            self.closeCurrentProject()

        return closeProject

    def onSaveProjectActionTriggered(self):
        logger.debug("Save Project action triggered")
        def save():
            self.thunkEventHandler.post( partial(self.handleAppletGuiControlSignal, 0, ControlCommand.DisableAll ) )
            try:
                self.projectManager.saveProject()
            except ProjectManager.SaveError, err:
                self.thunkEventHandler.post( partial( QMessageBox.warning, self, "Error Attempting Save", str(err) ) ) 
            self.thunkEventHandler.post( partial(self.handleAppletGuiControlSignal, 0, ControlCommand.Pop ) )
        
        saveThread = threading.Thread( target=save )
        saveThread.start()
        
        return saveThread # Return the thread so non-gui users (e.g. unit tests) can join it if they want to.

    def onSaveProjectAsActionTriggered(self):
        logger.debug("SaveAs Project action triggered")
        
        # Try to guess a good default project name, e.g. MyProject2.ilp 
        currentPath, ext = os.path.splitext(self.projectManager.currentProjectPath)
        m = re.match("(.*)_(\d+)", currentPath)
        if m:
            baseName = m.groups()[0]
            projectNum = int(m.groups()[1]) + 1
        else:
            baseName = currentPath
            projectNum = 2
        
        defaultNewPath = "{}_{}{}".format(baseName, projectNum, ext)

        newPath = self.getProjectPathToCreate(defaultNewPath, caption="Select New Project Name")
        if newPath == self.projectManager.currentProjectPath:
            # If the new path is the same as the old one, then just do a regular save
            self.onSaveProjectActionTriggered()
        elif newPath is not None:
            def saveAs():
                self.thunkEventHandler.post( partial(self.handleAppletGuiControlSignal, 0, ControlCommand.DisableAll ) )
                
                try:
                    self.projectManager.saveProjectAs( newPath )
                except ProjectManager.SaveError, err:
                    self.thunkEventHandler.post( partial( QMessageBox.warning, self, "Error Attempting Save", str(err) ) ) 
                self.updateShellProjectDisplay()
                self.thunkEventHandler.post( partial(self.handleAppletGuiControlSignal, 0, ControlCommand.Pop ) )

            saveThread = threading.Thread( target=saveAs )
            saveThread.start()

    def onSaveProjectSnapshotActionTriggered(self):
        logger.debug("Saving Snapshot")
        currentPath, ext = os.path.splitext(self.projectManager.currentProjectPath)
        defaultSnapshot = currentPath + "_snapshot" + ext
        
        snapshotPath = self.getProjectPathToCreate(defaultSnapshot, caption="Create Project Snapshot")
        if snapshotPath is not None:
            try:
                self.projectManager.saveProjectSnapshot(snapshotPath)
            except ProjectManager.SaveError, err:
                QMessageBox.warning( self, "Error Attempting Save Snapshot", str(err) )

    def closeEvent(self, closeEvent):
        """
        Reimplemented from QWidget.  Ignore the close event if the user has unsaved data and changes his mind.
        """
        if self.confirmQuit():
            self.closeAndQuit()
        else:
            closeEvent.ignore()
    
    def onQuitActionTriggered(self, force=False, quitApp=True):
        """
        The user wants to quit the application.
        Check his project for unsaved data and ask if he really means it.
        Args:
            force - Don't check the project for unsaved data.
            quitApp - For testing purposes, set this to False if you just want to close the main window without quitting the app.
        """
        logger.info("Quit Action Triggered")
        
        if force or self.confirmQuit():
            self.closeAndQuit(quitApp)
        
    def confirmQuit(self):
        if self.projectManager:
            dirtyApplets = self.projectManager.getDirtyAppletNames()
            if len(dirtyApplets) > 0:
                message = "Your project has unsaved data.  Are you sure you want to discard your changes and quit?\n"
                message += "(Unsaved changes in: {})".format( ', '.join(dirtyApplets) )
                buttons = QMessageBox.Discard | QMessageBox.Cancel
                response = QMessageBox.warning(self, "Discard unsaved changes?", message, buttons, defaultButton=QMessageBox.Cancel)
                if response == QMessageBox.Cancel:
                    return False

        return self._recorderGui.confirmQuit()

    def closeAndQuit(self, quitApp=True):
        PreferencesManager().set( 'shell', 'startscreenSize', (self.size().width(),self.size().height()))
        
        if self.projectManager is not None:
            self.projectManager.cleanUp()
            self.projectManager = None # Destroy project manager
        
        # Stop the thread that checks for log config changes.
        ilastik.ilastik_logging.stopUpdates()

        # Close the window first, so applets can reimplement hideEvent() and such.
        self.close()
        
        # For testing purposes, sometimes this function is called even though we don't want to really quit.
        if quitApp:
            qApp.quit()

    def updateAppletControlStates(self):
        """
        Enable or disable all controls of all applets according to their disable count.
        """
        for applet_index, applet in enumerate(self._applets):
            enabled = self._disableCounts[applet_index] == 0

            applet.getMultiLaneGui().setEnabled( enabled and self.enableWorkflow )
        
            # Apply to the applet bar drawer headings, too
            if applet_index < self.appletBar.count():
                enable_applet = (enabled and self.enableWorkflow)
                
                # Unfortunately, Qt will auto-select a different drawer if 
                #  we try to disable the currently selected drawer.
                # That can cause lots of problems for us (e.g. it trigger's the
                #  creation of applet guis that haven't been created yet.)
                # Therefore, only disable the title button of a drawer if it isn't already selected.
                if enable_applet or self.appletBar.currentIndex() != applet_index:
                    self.appletBar.setItemEnabled(applet_index, enable_applet)
assert issubclass( IlastikShell, ShellABC ), "IlastikShell does not satisfy the generic shell interface!"
