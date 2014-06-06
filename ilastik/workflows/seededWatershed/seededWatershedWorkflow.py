###############################################################################
#   ilastik: interactive learning and segmentation toolkit
#
#       Copyright (C) 2011-2014, the ilastik developers
#                                <team@ilastik.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# In addition, as a special exception, the copyright holders of
# ilastik give you permission to combine ilastik with applets,
# workflows and plugins which are not covered under the GNU
# General Public License.
#
# See the LICENSE file for details. License information is also available
# on the ilastik web site at:
#		   http://ilastik.org/license.html
###############################################################################
from ilastik.workflow import Workflow

from lazyflow.graph import Graph

from ilastik.applets.dataSelection import DataSelectionApplet
from ilastik.applets.seededWatershed import SeededWatershedApplet

class SeededWatershedWorkflow(Workflow):
    def __init__( self, shell, headless, workflow_cmdline_args, project_creation_args, *args, **kwargs):
        # Create a graph to be shared by all operators
        graph = Graph()
        super(SeededWatershedWorkflow, self).__init__( shell, headless, workflow_cmdline_args, project_creation_args, graph=graph, *args, **kwargs )
        self._applets = []

        # Create applets
        self.dataSelectionApplet = DataSelectionApplet(self, 
                                                       "Input Data", 
                                                       "Input Data", 
                                                       supportIlastik05Import=True, 
                                                       batchDataGui=False,
                                                       force5d=True)
        self.seededWatershedApplet = SeededWatershedApplet(self, "Seeded Watershed")

        opDataSelection = self.dataSelectionApplet.topLevelOperator
        opDataSelection.DatasetRoles.setValue( ["Raw Data", "Mask"] )

        self._applets.append( self.dataSelectionApplet )
        self._applets.append( self.seededWatershedApplet )

    def connectLane(self, laneIndex):
        opDataSelection = self.dataSelectionApplet.topLevelOperator.getLane(laneIndex)
        opSeededWatershed = self.seededWatershedApplet.topLevelOperator.getLane(laneIndex)
        
        # Connect top-level operators
        opSeededWatershed.InputImage.connect( opDataSelection.ImageGroup[0] )
        opSeededWatershed.Mask.connect( opDataSelection.ImageGroup[1] )
        opSeededWatershed.LabelsAllowedFlag.setValue(True)
        opSeededWatershed.FreezeCache.setValue(True)

    @property
    def applets(self):
        return self._applets

    @property
    def imageNameListSlot(self):
        return self.dataSelectionApplet.topLevelOperator.ImageName
