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
#           http://ilastik.org/license.html
###############################################################################
import os
import argparse
from ilastik.applets.base.applet import Applet
from ilastik.applets.dataExport.dataExportApplet import DataExportApplet
from ilastik.applets.dataSelection import DataSelectionApplet
from opSimpleBatch import OpSimpleBatch
from ilastik.utility import OpMultiLaneWrapper

class SimpleBatchApplet( Applet ):
    """
    
    """
    def __init__( self, workflow, title="Batch Processing" ):
        self.__topLevelOperator = OpSimpleBatch( parent=workflow )
        super(SimpleBatchApplet, self).__init__(title, syncWithImageIndex=False)

        self._gui = None
        self._title = title
        
        # This flag is set by the gui and checked by the workflow        
        self.busy = False
        
    @property
    def dataSerializers(self):
        # No serializers for now.
        return []

    @property
    def topLevelOperator(self):
        return self.__topLevelOperator

    def getMultiLaneGui(self):
        if self._gui is None:
            from simpleBatchGui import SimpleBatchGui
            self._gui = SimpleBatchGui( self, self.topLevelOperator )
        return self._gui

    @classmethod
    def parse_known_cmdline_args(cls, cmdline_args, role_names):
        export_args, unused_args = DataExportApplet.parse_known_cmdline_args(cmdline_args)
        input_args, unused_args = DataSelectionApplet.parse_known_cmdline_args(unused_args, role_names)
        return input_args, export_args, unused_args

    def configure_operator_with_parsed_args(self, input_args, export_args):
        # Configure input paths
        role_names = self.topLevelOperator.opDataSelectionGroup.DatasetRoles.value
        role_paths = DataSelectionApplet.role_paths_from_parsed_args(input_args, role_names)
        self.topLevelOperator.FilePaths.setValue( role_paths.values() )
        
        # Configure export settings
        DataExportApplet._configure_operator_with_parsed_args( export_args, self.topLevelOperator.opDataExport )
