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

from ilastik.workflow import Workflow

from lazyflow.graph import Graph
from lazyflow.roi import TinyVector

from ilastik.applets.dataSelection import DataSelectionApplet
from ilastik.applets.inputPreprocessing import InputPreprocessingApplet
from ilastik.applets.dataExport.dataExportApplet import DataExportApplet

import logging
logger = logging.getLogger(__name__)

class InputPreprocessingWorkflow(Workflow):
    workflowName = "Input Preprocessing"
    def __init__(self, shell, headless, workflow_cmdline_args, project_creation_args, *args, **kwargs):
        
        # Create a graph to be shared by all operators
        graph = Graph()
        super(InputPreprocessingWorkflow, self).__init__(shell, 
                                                         headless, 
                                                         workflow_cmdline_args, 
                                                         project_creation_args, 
                                                         graph=graph, 
                                                         *args, **kwargs)
        self._applets = []

        # Create applets 
        self.dataSelectionApplet = DataSelectionApplet(self, 
                                                       "Input Data", 
                                                       "Input Data", 
                                                       supportIlastik05Import=True, 
                                                       batchDataGui=False,
                                                       force5d=True)

        self.inputPreprocessingApplet = InputPreprocessingApplet(self, "Input Preprocessing")
        
        self.dataExportApplet = DataExportApplet(self, "Data Export")

        opDataSelection = self.dataSelectionApplet.topLevelOperator
        opDataSelection.DatasetRoles.setValue( ["Raw Data"] )

        self._applets.append( self.dataSelectionApplet )
        self._applets.append( self.inputPreprocessingApplet )
        self._applets.append( self.dataExportApplet )

        self._workflow_cmdline_args = workflow_cmdline_args

    def onProjectLoaded(self, projectManager):
        """
        Overridden from Workflow base class.  Called by the Project Manager.
        """
        logger.info( "InputPreprocessingWorkflow Project was opened with the following args: " )
        logger.info( self._workflow_cmdline_args )

    def connectLane(self, laneIndex):
        opDataSelectionView = self.dataSelectionApplet.topLevelOperator.getLane(laneIndex)
        opInputPreprocessing = self.inputPreprocessingApplet.topLevelOperator.getLane(laneIndex)
        opDataExportView = self.dataExportApplet.topLevelOperator.getLane(laneIndex)

        # Connect top-level operators
        opInputPreprocessing.Input.connect( opDataSelectionView.ImageGroup[0] )
        opInputPreprocessing.RawDatasetInfo.connect( opDataSelectionView.DatasetGroup[0] )

        opDataExportView.RawData.connect( opInputPreprocessing.CroppedImage )
        opDataExportView.Input.connect( opInputPreprocessing.Output )
        opDataExportView.RawDatasetInfo.connect( opDataSelectionView.DatasetGroup[0] )
        opDataExportView.WorkingDirectory.connect( opDataSelectionView.WorkingDirectory )

    @property
    def applets(self):
        return self._applets

    @property
    def imageNameListSlot(self):
        return self.dataSelectionApplet.topLevelOperator.ImageName

    def handleAppletStateUpdateRequested(self):
        """
        Overridden from Workflow base class
        Called when an applet has fired the :py:attr:`Applet.statusUpdateSignal`
        """
        # If no data, nothing else is ready.
        opDataSelection = self.dataSelectionApplet.topLevelOperator
        input_ready = len(opDataSelection.ImageGroup) > 0

        opDataExport = self.dataExportApplet.topLevelOperator
        export_data_ready = input_ready and \
                            len(opDataExport.Input) > 0 and \
                            opDataExport.Input[0].ready() and \
                            (TinyVector(opDataExport.Input[0].meta.shape) > 0).all()

        self._shell.setAppletEnabled(self.inputPreprocessingApplet, input_ready)
        self._shell.setAppletEnabled(self.dataExportApplet, export_data_ready)
        
        # Lastly, check for certain "busy" conditions, during which we 
        #  should prevent the shell from closing the project.
        busy = False
        busy |= self.dataSelectionApplet.busy
        busy |= self.dataExportApplet.busy
        self._shell.enableProjectChanges( not busy )

