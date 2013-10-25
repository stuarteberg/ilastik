import sys
import argparse
import logging
logger = logging.getLogger(__name__)

import threading
import numpy

from ilastik.workflow import Workflow

from ilastik.applets.pixelClassification import PixelClassificationApplet, PixelClassificationDataExportApplet
from ilastik.applets.projectMetadata import ProjectMetadataApplet
from ilastik.applets.dataSelection import DataSelectionApplet
from ilastik.applets.featureSelection import FeatureSelectionApplet

from ilastik.applets.featureSelection.opFeatureSelection import OpFeatureSelection
from ilastik.applets.pixelClassification.opPixelClassification import OpPredictionPipeline

from lazyflow.roi import TinyVector
from lazyflow.graph import Graph, InputSlot, OutputSlot, Operator, OperatorWrapper
from lazyflow.operators.generic import OpTransposeSlots, OpSelectSubslot

from ilastik.applets.dataExport.sharedPipelineWrapper import SharedPipelineWrapper

class PixelClassificationWorkflow(Workflow):
    
    workflowName = "Pixel Classification"
    workflowDescription = "This is obviously self-explanoratory."
    defaultAppletIndex = 1 # show DataSelection by default
    
    @property
    def applets(self):
        return self._applets

    @property
    def imageNameListSlot(self):
        return self.dataSelectionApplet.topLevelOperator.ImageName

    def __init__(self, shell, headless, workflow_cmdline_args, appendBatchOperators=True, *args, **kwargs):
        # Create a graph to be shared by all operators
        graph = Graph()
        super( PixelClassificationWorkflow, self ).__init__( shell, headless, graph=graph, *args, **kwargs )
        self._applets = []
        self._workflow_cmdline_args = workflow_cmdline_args

        data_instructions = "Select your input data using the 'Raw Data' tab shown on the right"

        # Parse workflow-specific command-line args
        parser = argparse.ArgumentParser()
        parser.add_argument('--filter', help="pixel feature filter implementation.", choices=['Original', 'Refactored', 'Interpolated'], default='Original')
        parsed_args, unused_args = parser.parse_known_args(workflow_cmdline_args)
        self.filter_implementation = parsed_args.filter
        
        # Applets for training (interactive) workflow 
        self.projectMetadataApplet = ProjectMetadataApplet()
        self.dataSelectionApplet = DataSelectionApplet( self,
                                                        "Input Data",
                                                        "Input Data",
                                                        supportIlastik05Import=True,
                                                        batchDataGui=False,
                                                        instructionText=data_instructions )
        opDataSelection = self.dataSelectionApplet.topLevelOperator
        opDataSelection.DatasetRoles.setValue( ['Raw Data'] )

        self.featureSelectionApplet = FeatureSelectionApplet(self, "Feature Selection", "FeatureSelections", self.filter_implementation)

        self.pcApplet = PixelClassificationApplet(self, "PixelClassification")
        opClassify = self.pcApplet.topLevelOperator

        self.dataExportApplet = PixelClassificationDataExportApplet(self, "Prediction Export")
        opDataExport = self.dataExportApplet.topLevelOperator
        opDataExport.PmapColors.connect( opClassify.PmapColors )
        opDataExport.LabelNames.connect( opClassify.LabelNames )
        opDataExport.WorkingDirectory.connect( opDataSelection.WorkingDirectory )

        # Expose for shell
        self._applets.append(self.projectMetadataApplet)
        self._applets.append(self.dataSelectionApplet)
        self._applets.append(self.featureSelectionApplet)
        self._applets.append(self.pcApplet)
        self._applets.append(self.dataExportApplet)

        self._batch_input_args = None
        self._batch_export_args = None

        self.batchInputApplet = None
        self.batchResultsApplet = None
        if appendBatchOperators:
            # Create applets for batch workflow
            self.batchInputApplet = DataSelectionApplet(self, "Batch Prediction Input Selections", "Batch Inputs", supportIlastik05Import=False, batchDataGui=True)
            self.batchResultsApplet = PixelClassificationDataExportApplet(self, "Batch Prediction Output Locations", isBatch=True)
    
            # Expose in shell        
            self._applets.append(self.batchInputApplet)
            self._applets.append(self.batchResultsApplet)
    
            # Connect batch workflow (NOT lane-based)
            self._initBatchWorkflow()

            if unused_args:
                # We parse the export setting args first.  All remaining args are considered input files by the input applet.
                self._batch_export_args, unused_args = self.batchResultsApplet.parse_known_cmdline_args( unused_args )
                self._batch_input_args, unused_args = self.batchInputApplet.parse_known_cmdline_args( unused_args )
    
        if unused_args:
            logger.warn("Unused command-line args: {}".format( unused_args ))

    def connectLane(self, laneIndex):
        # Get a handle to each operator
        opData = self.dataSelectionApplet.topLevelOperator.getLane(laneIndex)
        opTrainingFeatures = self.featureSelectionApplet.topLevelOperator.getLane(laneIndex)
        opClassify = self.pcApplet.topLevelOperator.getLane(laneIndex)
        opDataExport = self.dataExportApplet.topLevelOperator.getLane(laneIndex)
        
        # Input Image -> Feature Op
        #         and -> Classification Op (for display)
        opTrainingFeatures.InputImage.connect( opData.Image )
        opClassify.InputImages.connect( opData.Image )
        
        # Feature Images -> Classification Op (for training, prediction)
        opClassify.FeatureImages.connect( opTrainingFeatures.OutputImage )
        opClassify.CachedFeatureImages.connect( opTrainingFeatures.CachedOutputImage )
        
        # Training flags -> Classification Op (for GUI restrictions)
        opClassify.LabelsAllowedFlags.connect( opData.AllowLabels )

        # Data Export connections
        opDataExport.RawData.connect( opData.ImageGroup[0] )
        opDataExport.Input.connect( opClassify.HeadlessPredictionProbabilities )
        opDataExport.RawDatasetInfo.connect( opData.DatasetGroup[0] )
        opDataExport.ConstraintDataset.connect( opData.ImageGroup[0] )

    class OpPixelClassificationBatchPipeline(Operator):
        Input = InputSlot()
        
        Scales = InputSlot()
        FeatureIds = InputSlot()
        SelectionMatrix = InputSlot()
        
        Classifier = InputSlot()
        NumClasses = InputSlot()
        
        Output = OutputSlot()
                
        def __init__(self, parent, filter_implementation):
            super( PixelClassificationWorkflow.OpPixelClassificationBatchPipeline, self ).__init__(parent)
            
            ## Create additional batch workflow operators
            opBatchFeatures = OpFeatureSelection( parent=self, filter_implementation=filter_implementation )
            opBatchFeatures.InputImage.connect( self.Input )
            opBatchPredictionPipeline = OpPredictionPipeline( parent=self )

            opBatchFeatures.Scales.connect( self.Scales )
            opBatchFeatures.FeatureIds.connect( self.FeatureIds )
            opBatchFeatures.SelectionMatrix.connect( self.SelectionMatrix )
                
            # Classifier and NumClasses are provided by the interactive workflow
            opBatchPredictionPipeline.Classifier.connect( self.Classifier )
            opBatchPredictionPipeline.FreezePredictions.setValue( False )
            opBatchPredictionPipeline.NumClasses.connect( self.NumClasses )
    
            # Connect Image pathway:
            # Input Image -> Features Op -> Prediction Op -> Export
            opBatchFeatures.InputImage.connect( self.Input )
            opBatchPredictionPipeline.FeatureImages.connect( opBatchFeatures.OutputImage )
    
            # We don't actually need the cached path in the batch pipeline.
            # Just connect the uncached features here to satisfy the operator.
            opBatchPredictionPipeline.CachedFeatureImages.connect( opBatchFeatures.OutputImage )

            self.Output.connect( opBatchPredictionPipeline.HeadlessPredictionProbabilities )

        def setupOutputs(self):
            pass
        
        def execute(self, *args):
            assert False, "Shouldn't get here"
        
        def propagateDirty(self, *args):
            pass # Nothing to do here.

    class OpMultiImagePixelClassificationBatchPipeline(Operator):
        Inputs = InputSlot(level=1)
        
        Scales = InputSlot()
        FeatureIds = InputSlot()
        SelectionMatrix = InputSlot()
        
        Classifier = InputSlot()
        NumClasses = InputSlot()
        
        Outputs = OutputSlot(level=1)
        
        def __init__(self, pipeline_instance, *args, **kwargs):
            cls = PixelClassificationWorkflow.OpMultiImagePixelClassificationBatchPipeline
            super( cls, self ).__init__( *args, **kwargs )
            self._pipeline = pipeline_instance
            
            self._selected_index = -1
            self._lock = threading.Lock()
            
            self._pipeline.Scales.connect( self.Scales )
            self._pipeline.FeatureIds.connect( self.FeatureIds )
            self._pipeline.SelectionMatrix.connect( self.SelectionMatrix )
            self._pipeline.Classifier.connect( self.Classifier )
            self._pipeline.NumClasses.connect( self.NumClasses )

        def setupOutputs(self):
            if self._selected_index == -1:
                # Find the first ready slot and connect it.
                for index, slot in enumerate(self.Input):
                    if slot.ready():
                        self._selected_index = index
                        break
                assert self._selected_index != -1
                self._pipeline.Input.disconnect()
                self._pipeline.Input.connect( self.Inputs[self._selected_index] )

            reference_outslot = self._pipeline.Output
            reference_taggedshape = reference_outslot.meta.getTaggedShape()

            self.Outputs.resize( self.Inputs )
            for index, outslot in enumerate( self.Outputs ):
                # We assume all slots have the same metadata except for shape
                tagged_shape = self.Inputs[index].meta.getTaggedShape()
                tagged_shape['c'] = reference_taggedshape['c']
                outslot.meta.assignFrom( reference_outslot.meta )
                outslot.meta.shape = tuple( tagged_shape.values() )

        def execute(self, slot, subindex, roi, result):
            image_index = subindex[0]
            
            # If necessary, hook up inner pipeline to the selected input
            with self._lock:
                self._selected_index = image_index
                if self._selected_index != image_index:
                    self._pipeline.Input.disconnect()
                    self._pipeline.Input.connect( self.Inputs[image_index] )

            # Simply forward the result from the inner pipeline
            self._pipeline.Output(roi.start, roi.stop).writeInto( result ).wait()
            return result

    def _initBatchWorkflow(self):
        """
        Connect the batch-mode top-level operators to the training workflow and to each other.
        """
        # Access applet operators from the training workflow
        opTrainingDataSelection = self.dataSelectionApplet.topLevelOperator
        opTrainingFeatures = self.featureSelectionApplet.topLevelOperator
        opClassify = self.pcApplet.topLevelOperator
        
        # Access the batch operators
        opBatchInputs = self.batchInputApplet.topLevelOperator
        opBatchResults = self.batchResultsApplet.topLevelOperator
        
        opBatchInputs.DatasetRoles.connect( opTrainingDataSelection.DatasetRoles )
        
        opSelectFirstLane = OperatorWrapper( OpSelectSubslot, parent=self )
        opSelectFirstLane.Inputs.connect( opTrainingDataSelection.ImageGroup )
        opSelectFirstLane.SubslotIndex.setValue(0)
       
        opSelectFirstRole = OpSelectSubslot( parent=self )
        opSelectFirstRole.Inputs.connect( opSelectFirstLane.Output )
        opSelectFirstRole.SubslotIndex.setValue(0)
        
        opBatchResults.ConstraintDataset.connect( opSelectFirstRole.Output )
        
        ## Connect Operators ##
        opTranspose = OpTransposeSlots( parent=self )
        opTranspose.OutputLength.setValue(1)
        opTranspose.Inputs.connect( opBatchInputs.DatasetGroup )
        
        # Provide dataset paths from data selection applet to the batch export applet
        opBatchResults.RawDatasetInfo.connect( opTranspose.Outputs[0] )
        opBatchResults.WorkingDirectory.connect( opBatchInputs.WorkingDirectory )

        # Provide these for the gui
        opBatchResults.RawData.connect( opBatchInputs.Image )
        opBatchResults.PmapColors.connect( opClassify.PmapColors )
        opBatchResults.LabelNames.connect( opClassify.LabelNames )

#        ## Create additional batch workflow operators
#        opBatchFeatures = OperatorWrapper( OpFeatureSelection, operator_kwargs={'filter_implementation': self.filter_implementation}, parent=self, promotedSlotNames=['InputImage'] )
#        opBatchPredictionPipeline = OperatorWrapper( OpPredictionPipeline, parent=self )
#        
#        # Connect (clone) the feature operator inputs from 
#        #  the interactive workflow's features operator (which gets them from the GUI)
#        opBatchFeatures.Scales.connect( opTrainingFeatures.Scales )
#        opBatchFeatures.FeatureIds.connect( opTrainingFeatures.FeatureIds )
#        opBatchFeatures.SelectionMatrix.connect( opTrainingFeatures.SelectionMatrix )
#        
#        # Classifier and NumClasses are provided by the interactive workflow
#        opBatchPredictionPipeline.Classifier.connect( opClassify.Classifier )
#        opBatchPredictionPipeline.FreezePredictions.setValue( False )
#        opBatchPredictionPipeline.NumClasses.connect( opClassify.NumClasses )
#
#        # We don't actually need the cached path in the batch pipeline.
#        # Just connect the uncached features here to satisfy the operator.
#        opBatchPredictionPipeline.CachedFeatureImages.connect( opBatchFeatures.OutputImage )        
#
#        # For headless mode.
#        self.opBatchPredictionPipeline = opBatchPredictionPipeline
#
#        # Connect Image pathway:
#        # Input Image -> Features Op -> Prediction Op -> Export
#        opBatchFeatures.InputImage.connect( opBatchInputs.Image )
#        opBatchPredictionPipeline.FeatureImages.connect( opBatchFeatures.OutputImage )
#        opBatchResults.Input.connect( opBatchPredictionPipeline.HeadlessPredictionProbabilities )

        opSharedBatchPipeline = PixelClassificationWorkflow.OpPixelClassificationBatchPipeline( parent=self, filter_implementation=self.filter_implementation )
#        opBatchWrapper = SharedPipelineWrapper( opSharedBatchPipeline, \
#                                                ['Scales', 'FeatureIds', 'SelectionMatrix', 'Classifier', 'NumClasses' ],
#                                                parent=self )

        opBatchWrapper = PixelClassificationWorkflow.OpMultiImagePixelClassificationBatchPipeline(
                              opSharedBatchPipeline, parent=self )

        # Image input/output
        opBatchWrapper.Input.connect( opBatchInputs.Image )
        opBatchResults.Input.connect( opBatchWrapper.Output )

        # Settings (copied from interactive pipeline)
        opBatchWrapper.Scales.connect( opTrainingFeatures.Scales )
        opBatchWrapper.FeatureIds.connect( opTrainingFeatures.FeatureIds )
        opBatchWrapper.SelectionMatrix.connect( opTrainingFeatures.SelectionMatrix )
        opBatchWrapper.Classifier.connect( opClassify.Classifier )
        opBatchWrapper.NumClasses.connect( opClassify.NumClasses )

    def handleAppletStateUpdateRequested(self):
        """
        Overridden from Workflow base class
        Called when an applet has fired the :py:attr:`Applet.appletStateUpdateRequested`
        """
        # If no data, nothing else is ready.
        opDataSelection = self.dataSelectionApplet.topLevelOperator
        input_ready = len(opDataSelection.ImageGroup) > 0

        opFeatureSelection = self.featureSelectionApplet.topLevelOperator
        featureOutput = opFeatureSelection.OutputImage
        features_ready = input_ready and \
                         len(featureOutput) > 0 and  \
                         featureOutput[0].ready() and \
                         (TinyVector(featureOutput[0].meta.shape) > 0).all()

        opDataExport = self.dataExportApplet.topLevelOperator
        predictions_ready = features_ready and \
                            len(opDataExport.Input) > 0 and \
                            opDataExport.Input[0].ready() and \
                            (TinyVector(opDataExport.Input[0].meta.shape) > 0).all()

        # Problems can occur if the features or input data are changed during live update mode.
        # Don't let the user do that.
        opPixelClassification = self.pcApplet.topLevelOperator
        live_update_active = not opPixelClassification.FreezePredictions.value

        self._shell.setAppletEnabled(self.dataSelectionApplet, not live_update_active)
        self._shell.setAppletEnabled(self.featureSelectionApplet, input_ready and not live_update_active)
        self._shell.setAppletEnabled(self.pcApplet, features_ready)
        self._shell.setAppletEnabled(self.dataExportApplet, predictions_ready)
        
        # Training workflow must be fully configured before batch can be used
        self._shell.setAppletEnabled(self.batchInputApplet, predictions_ready)

        opBatchDataSelection = self.batchInputApplet.topLevelOperator
        batch_input_ready = predictions_ready and \
                            len(opBatchDataSelection.ImageGroup) > 0
        self._shell.setAppletEnabled(self.batchResultsApplet, batch_input_ready)
        
        # Lastly, check for certain "busy" conditions, during which we 
        #  should prevent the shell from closing the project.
        busy = False
        busy |= self.dataSelectionApplet.busy
        busy |= self.featureSelectionApplet.busy
        busy |= self.dataExportApplet.busy
        self._shell.enableProjectChanges( not busy )

#    def getHeadlessOutputSlot(self, slotId):
#        # "Regular" (i.e. with the images that the user selected as input data)
#        if slotId == "Predictions":
#            return self.pcApplet.topLevelOperator.HeadlessPredictionProbabilities
#        elif slotId == "PredictionsUint8":
#            return self.pcApplet.topLevelOperator.HeadlessUint8PredictionProbabilities
#        # "Batch" (i.e. with the images that the user selected as batch inputs).
#        elif slotId == "BatchPredictions":
#            return self.opBatchPredictionPipeline.HeadlessPredictionProbabilities
#        if slotId == "BatchPredictionsUint8":
#            return self.opBatchPredictionPipeline.HeadlessUint8PredictionProbabilities
#        
#        raise Exception("Unknown headless output slot")
    
    def onProjectLoaded(self, projectManager):
        """
        Overridden from Workflow base class.  Called by the Project Manager.
        
        If the user provided command-line arguments, use them to configure 
        the workflow for batch mode and export all results.
        (This workflow's headless mode supports only batch mode for now.)
        """
        # Configure the batch data selection operator.
        if self._batch_input_args and self._batch_input_args.input_files: 
            self.batchInputApplet.configure_operator_with_parsed_args( self._batch_input_args )
        
        # Configure the data export operator.
        if self._batch_export_args:
            self.batchResultsApplet.configure_operator_with_parsed_args( self._batch_export_args )

        if self._headless and self._batch_input_args and self._batch_export_args:
            
            # Make sure we're using the up-to-date classifier.
            self.pcApplet.topLevelOperator.FreezePredictions.setValue(False)
        
            # Now run the batch export and report progress....
            opBatchDataExport = self.batchResultsApplet.topLevelOperator
            for i, opExportDataLaneView in enumerate(opBatchDataExport):
                print "Exporting result {} to {}".format(i, opExportDataLaneView.ExportPath.value)
    
                sys.stdout.write( "Result {}/{} Progress: ".format( i, len( opBatchDataExport ) ) )
                def print_progress( progress ):
                    sys.stdout.write( "{} ".format( progress ) )
    
                # If the operator provides a progress signal, use it.
                slotProgressSignal = opExportDataLaneView.progressSignal
                slotProgressSignal.subscribe( print_progress )
                opExportDataLaneView.run_export()
                
                # Finished.
                sys.stdout.write("\n")

