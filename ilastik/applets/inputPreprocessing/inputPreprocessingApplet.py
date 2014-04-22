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
import argparse
from ilastik.applets.base.applet import Applet
from opInputPreprocessing import OpInputPreprocessing
from inputPreprocessingSerializer import InputPreprocessingSerializer
from ilastik.utility import OpMultiLaneWrapper

class InputPreprocessingApplet( Applet ):
    """
    
    """
    def __init__( self, workflow, title ):
        # Designed to be subclassed: If the subclass defined its own top-level operator,
        #  don't create one here.
        self.__topLevelOperator = None
        if self.topLevelOperator is None:
            self.__topLevelOperator = OpMultiLaneWrapper( OpInputPreprocessing, parent=workflow, broadcastingSlotNames=[])
        super(InputPreprocessingApplet, self).__init__(title, syncWithImageIndex=True)

        self._gui = None
        self._title = title
        
        # This applet is designed to be subclassed.
        # If the user provided his own serializer, don't create one here.
        self.__serializers = None
        if self.dataSerializers is None:
            self.__serializers = [ InputPreprocessingSerializer(self.topLevelOperator, title) ]

        # This flag is set by the gui and checked by the workflow        
        self.busy = False
        
    @property
    def dataSerializers(self):
        return self.__serializers

    @property
    def topLevelOperator(self):
        return self.__topLevelOperator

    def getMultiLaneGui(self):
        if self._gui is None:
            from inputPreprocessingGui import InputPreprocessingGui
            self._gui = InputPreprocessingGui( self, self.topLevelOperator )
        return self._gui

    def parse_known_cmdline_args(self, cmdline_args):
        """TODO"""

    def configure_operator_with_parsed_args(self, parsed_args):
        """TODO"""
