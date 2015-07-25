import os
import copy
import logging
logger = logging.getLogger(__name__)

import numpy

from lazyflow.graph import Operator, InputSlot, OutputSlot
from lazyflow.utility import PathComponents, getPathVariants, format_known_keys, OrderedSignal
from lazyflow.operators.ioOperators import OpInputDataReader, OpFormattedDataExport
from lazyflow.operators.generic import OpSubRegion
from lazyflow.operators.valueProviders import OpMetadataInjector

from ilastik.applets.dataSelection import DataSelectionApplet
from ilastik.applets.dataSelection.opDataSelection import OpDataSelectionGroup, DatasetInfo

class OpSimpleBatch(Operator):
    TemplateDatasetInfo = InputSlot(optional=True)   # Value slot: A DatasetInfo() object that will be reused for 
                                                     # all datasets in all roles (except for the filepath field)
                                                     # TODO: It would probably be better to allow a separate template for each role.
    FilePaths = InputSlot()  # Value slot: A list-of-lists, e.g.:
                             # [[/path/to/raw-data-1.png, /path/to/raw-data-2.png, /path/to/raw-data-3.png],
                             #  [/path/to/segments-1.png, None,                    /path/to/segments-3.png]]

    def __init__( self, *args, **kwargs ):
        super( OpSimpleBatch, self ).__init__( *args, **kwargs )
        self.progressSignal = OrderedSignal()
        self.opDataSelectionGroup = None
        self.opDataExport = None

    def configure( self, opDataSelectionGroup, opDataExport ):
        assert isinstance(opDataSelectionGroup, OpDataSelectionGroup)
        self.opDataSelectionGroup = opDataSelectionGroup
        self.opDataExport = opDataExport
     
    def setupOutputs(self):
        pass
    
    def propagateDirty(self, slot, subindex, roi):
        pass

    def execute(self, slot, subindex, roi, result):
        pass
        
    def run_export(self):
        assert self.opDataSelectionGroup and self.opDataExport, "Not configured yet."

        if self.TemplateDatasetInfo.ready():
            dataset_info = self.TemplateDatasetInfo.value
        else:
            dataset_info = DatasetInfo()
        assert dataset_info.location == DatasetInfo.Location.FileSystem

        assert self.FilePaths.ready()
        input_role_names = self.opDataSelectionGroup.DatasetRoles.value
        num_roles = len(input_role_names)
        filepath_lists = self.FilePaths.value
        assert len(filepath_lists) == num_roles, "filepath list doesn't match the roles."
        num_datasets = len(filepath_lists[0])

        # Prepare
        self.opDataSelectionGroup.DatasetGroup.resize( num_roles )
        assert isinstance(filepath_lists, (list, tuple))
        assert len(filepath_lists) == len(input_role_names)

        # All lists must have the same length.
        # If one role is optional, None must be provided in that place.
        for filepath_list in filepath_lists:
            assert len(filepath_list) == len(filepath_lists[0])
        
        # Transpose from l[role][index] to l[index][role]
        files_by_index = zip(*filepath_lists)

        # Export each in turn. (Not in parallel...)
        for filepaths in files_by_index:
            # Disconnect existing values
            self.opDataExport.RawDatasetInfo.disconnect()
            for slot in reversed(self.opDataSelectionGroup.DatasetGroup):
                slot.disconnect()
            
            logger.info("Preparing {}".format( filepaths[0] ))

            # Configure inputs
            for role_index, filepath in enumerate(filepaths):
                if filepath:
                    default_info = DataSelectionApplet.create_default_headless_dataset_info( filepath )                    
                    dataset_info.filePath = default_info.filePath
                    dataset_info.nickname = default_info.nickname
                    self.opDataSelectionGroup.DatasetGroup[role_index].setValue( copy.copy(dataset_info) )
                    
            # Configure export operator
            self.opDataExport.RawDatasetInfo.connect( self.opDataSelectionGroup.DatasetGroup[0] )
            
            assert self.opDataExport.ImageToExport.ready()
            assert self.opDataExport.ExportPath.ready()

            # Perform export
            logger.info("Exporting to {}".format( self.opDataExport.ExportPath.value ))
            self.opDataExport.run_export()
        
        logger.info("ALL EXPORTS COMPLETE.")
