from PyQt4.QtGui import *
from PyQt4 import uic
from PyQt4.QtCore import pyqtSignal, pyqtSlot, Qt, QObject

from ilastik.widgets.featureTableWidget import FeatureEntry
from ilastik.widgets.featureDlg import FeatureDlg
from ilastik.applets.objectExtraction.opObjectExtraction import OpRegionFeatures3d
from ilastik.applets.objectExtraction.opObjectExtraction import default_features_key

import os
import numpy
import weakref
from functools import partial

from ilastik.utility import bind
from ilastik.utility.gui import ThreadRouter, threadRouted
from lazyflow.operators import OpSubRegion

import logging
logger = logging.getLogger(__name__)

from ilastik.applets.layerViewer.layerViewerGui import LayerViewerGui
from ilastik.applets.labeling.labelingGui import LabelingGui

import volumina.colortables as colortables
from volumina.api import \
    LazyflowSource, GrayscaleLayer, ColortableLayer, AlphaModulatedLayer, \
    ClickableColortableLayer, LazyflowSinkSource

from volumina.interpreter import ClickInterpreter

def _listReplace(old, new):
    if len(old) > len(new):
        return new + old[len(new):]
    else:
        return new

from ilastik.applets.objectExtraction.objectExtractionGui import FeatureSelectionDialog


class FeatureSubSelectionDialog(FeatureSelectionDialog):
    def __init__(self, featureDict, selectedFeatures=None, parent=None, ndim=3):
        super(FeatureSubSelectionDialog, self).__init__(featureDict, selectedFeatures, parent, ndim)
        self.setObjectName("FeatureSubSelectionDialog")
        self.ui.spinBox_X.setEnabled(False)
        self.ui.spinBox_Y.setEnabled(False)
        self.ui.spinBox_Z.setEnabled(False)
        self.ui.spinBox_X.setVisible(False)
        self.ui.spinBox_Y.setVisible(False)
        self.ui.spinBox_Z.setVisible(False)
        self.ui.marginLabel.setVisible(False)
        self.ui.label.setVisible(False)
        self.ui.label_2.setVisible(False)
        self.ui.label_z.setVisible(False)

class ObjectClassificationGui(LabelingGui):
    """A subclass of LabelingGui for labeling objects.

    Handles labeling objects, viewing the predicted results, and
    displaying warnings from the top level operator. Also provides a
    dialog for choosing subsets of the precalculated features provided
    by the object extraction applet.

    """

    def centralWidget(self):
        return self

    def appletDrawers(self):
        # Get the labeling drawer from the base class
        labelingDrawer = super(ObjectClassificationGui, self).appletDrawers()[0][1]
        return [("Training", labelingDrawer)]

    def stopAndCleanUp(self):
        # Unsubscribe to all signals
        for fn in self.__cleanup_fns:
            fn()

        # Base class
        super(ObjectClassificationGui, self).stopAndCleanUp()

        # Ensure that we are NOT in interactive mode
        self.labelingDrawerUi.checkInteractive.setChecked(False)
        self.labelingDrawerUi.checkShowPredictions.setChecked(False)

    def __init__(self, parentApplet, op):
        self.__cleanup_fns = []
        # Tell our base class which slots to monitor
        labelSlots = LabelingGui.LabelingSlots()
        labelSlots.labelInput = op.LabelInputs
        labelSlots.labelOutput = op.LabelImages

        labelSlots.labelEraserValue = op.Eraser
        labelSlots.labelDelete = op.DeleteLabel

        labelSlots.maxLabelValue = op.NumLabels
        labelSlots.labelsAllowed = op.LabelsAllowedFlags
        labelSlots.labelNames = op.LabelNames
        
        # We provide our own UI file (which adds an extra control for
        # interactive mode) This UI file is copied from
        # pixelClassification pipeline
        #
        labelingDrawerUiPath = os.path.split(__file__)[0] + '/labelingDrawer.ui'

        # Base class init
        super(ObjectClassificationGui, self).__init__(parentApplet, labelSlots, op,
                                                      labelingDrawerUiPath,
                                                      crosshair=False)

        self.op = op
        self.applet = parentApplet

        self.threadRouter = ThreadRouter(self)
        op.Warnings.notifyDirty(self.handleWarnings)
        self.__cleanup_fns.append( partial( op.Warnings.unregisterDirty, self.handleWarnings ) )

        self._retained_weakrefs = []

        # unused
        self.labelingDrawerUi.savePredictionsButton.setEnabled(False)
        self.labelingDrawerUi.savePredictionsButton.setVisible(False)

        self.labelingDrawerUi.brushSizeComboBox.setEnabled(False)
        self.labelingDrawerUi.brushSizeComboBox.setVisible(False)
        
        self.labelingDrawerUi.brushSizeCaption.setVisible(False)

        self._colorTable16_forpmaps = self._createDefault16ColorColorTable()
        self._colorTable16_forpmaps[15] = QColor(Qt.black).rgba() #for objects with NaNs in features
        
        # button handlers
        self._interactiveMode = False
        self._showPredictions = False
        self._labelMode = True

        self.labelingDrawerUi.subsetFeaturesButton.clicked.connect(
            self.handleSubsetFeaturesClicked)
        self.labelingDrawerUi.checkInteractive.toggled.connect(
            self.handleInteractiveModeClicked)
        self.labelingDrawerUi.checkShowPredictions.toggled.connect(
            self.handleShowPredictionsClicked)

        #select all the features in the beginning
        cfn = None
        already_selected = None
        if self.op.ComputedFeatureNames.ready():
            cfn = self.op.ComputedFeatureNames[:].wait()
            
        if self.op.SelectedFeatures.ready():
            already_selected = self.op.SelectedFeatures[:].wait()
            
        if already_selected is None or len(already_selected)==0:
            if cfn is not None:
                already_selected = cfn
        
        self.op.SelectedFeatures.setValue(already_selected)
        
        nfeatures = 0
        
        if already_selected is not None:
            for plugin_features in already_selected.itervalues():
                nfeatures += len(plugin_features)
        self.labelingDrawerUi.featuresSubset.setText("{} features selected,\nsome may have multiple channels".format(nfeatures))

        # enable/disable buttons logic
        self.op.ObjectFeatures.notifyDirty(bind(self.checkEnableButtons))
        self.__cleanup_fns.append( partial( op.ObjectFeatures.unregisterDirty, bind(self.checkEnableButtons) ) )

        self.op.NumLabels.notifyDirty(bind(self.checkEnableButtons))
        self.__cleanup_fns.append( partial( op.NumLabels.unregisterDirty, bind(self.checkEnableButtons) ) )
        
        self.op.SelectedFeatures.notifyDirty(bind(self.checkEnableButtons))
        self.__cleanup_fns.append( partial( op.SelectedFeatures.unregisterDirty, bind(self.checkEnableButtons) ) )
        
        self.checkEnableButtons()

    @property
    def labelMode(self):
        return self._labelMode

    @labelMode.setter
    def labelMode(self, val):
        self.labelingDrawerUi.labelListView.allowDelete = val
        self.labelingDrawerUi.AddLabelButton.setEnabled(val)
        self._labelMode = val

    @property
    def interactiveMode(self):
        return self._interactiveMode

    @interactiveMode.setter
    def interactiveMode(self, val):
        logger.debug("setting interactive mode to '%r'" % val)
        self._interactiveMode = val
        self.labelingDrawerUi.checkInteractive.setChecked(val)
        if val:
            self.showPredictions = True
        self.labelMode = not val
        self.op.FreezePredictions.setValue(not val)

    @pyqtSlot()
    def handleInteractiveModeClicked(self):
        self.interactiveMode = self.labelingDrawerUi.checkInteractive.isChecked()

    @property
    def showPredictions(self):
        return self._showPredictions

    @showPredictions.setter
    def showPredictions(self, val):
        self._showPredictions = val
        self.labelingDrawerUi.checkShowPredictions.setChecked(val)
        for layer in self.layerstack:
            if "Prediction" in layer.name:
                layer.visible = val

        if self.labelMode and not val:
            self.labelMode = False
            # And hide all segmentation layers
            for layer in self.layerstack:
                if "Segmentation" in layer.name:
                    layer.visible = False

    @pyqtSlot()
    def handleShowPredictionsClicked(self):
        self.showPredictions = self.labelingDrawerUi.checkShowPredictions.isChecked()

    @pyqtSlot()
    def handleSubsetFeaturesClicked(self):
        mainOperator = self.topLevelOperatorView
        computedFeatures = mainOperator.ComputedFeatureNames([]).wait()
        if mainOperator.SelectedFeatures.ready():
            selectedFeatures = mainOperator.SelectedFeatures([]).wait()
        else:
            selectedFeatures = None

        ndim = 3
        at = mainOperator.RawImages.meta.axistags
        z_shape = mainOperator.RawImages.meta.shape[at.index('z')]
        if z_shape==1:
            ndim = 2
        dlg = FeatureSubSelectionDialog(computedFeatures,
                                        selectedFeatures=selectedFeatures, ndim=ndim)
        dlg.exec_()
        if dlg.result() == QDialog.Accepted:
            if len(dlg.selectedFeatures) == 0:
                self.interactiveMode = False
            mainOperator.SelectedFeatures.setValue(dlg.selectedFeatures)
            nfeatures = 0
            for plugin_features in dlg.selectedFeatures.itervalues():
                nfeatures += len(plugin_features)
            self.labelingDrawerUi.featuresSubset.setText("{} features selected,\nsome may have multiple channels".format(nfeatures))

    @pyqtSlot()
    def checkEnableButtons(self):
        feats_enabled = True
        predict_enabled = True
        labels_enabled = True

        if self.op.ComputedFeatureNames.ready():
            featnames = self.op.ComputedFeatureNames([]).wait()
            if len(featnames) == 0:
                feats_enabled = False
        else:
            feats_enabled = False

        if feats_enabled:
            if self.op.SelectedFeatures.ready():
                featnames = self.op.SelectedFeatures([]).wait()
                if len(featnames) == 0:
                    predict_enabled = False
            else:
                predict_enabled = False

            if self.op.NumLabels.ready():
                if self.op.NumLabels.value < 2:
                    predict_enabled = False
            else:
                predict_enabled = False
        else:
            predict_enabled = False

        if not predict_enabled:
            self.interactiveMode = False
            self.showPredictions = False

        self.labelingDrawerUi.subsetFeaturesButton.setEnabled(feats_enabled)
        self.labelingDrawerUi.checkInteractive.setEnabled(predict_enabled)
        self.labelingDrawerUi.checkShowPredictions.setEnabled(predict_enabled)
        self.labelingDrawerUi.AddLabelButton.setEnabled(labels_enabled)
        self.labelingDrawerUi.labelListView.allowDelete = True

        self.applet.predict_enabled = predict_enabled
        self.applet.appletStateUpdateRequested.emit()

    def initAppletDrawerUi(self):
        """
        Load the ui file for the applet drawer, which we own.
        """
        localDir = os.path.split(__file__)[0]

        # We don't pass self here because we keep the drawer ui in a
        # separate object.
        self.drawer = uic.loadUi(localDir+"/drawer.ui")

    ### Function dealing with label name and color consistency
    def _getNext(self, slot, parentFun, transform=None):
        numLabels = self.labelListData.rowCount()
        value = slot.value
        if numLabels < len(value):
            result = value[numLabels]
            if transform is not None:
                result = transform(result)
            return result
        else:
            return parentFun()

    def _onLabelChanged(self, parentFun, mapf, slot):
        parentFun()
        new = map(mapf, self.labelListData)
        old = slot.value
        slot.setValue(_listReplace(old, new))

    def getNextLabelName(self):
        return self._getNext(self.topLevelOperatorView.LabelNames,
                             super(ObjectClassificationGui, self).getNextLabelName)

    def getNextLabelColor(self):
        return self._getNext(
            self.topLevelOperatorView.LabelColors,
            super(ObjectClassificationGui, self).getNextLabelColor,
            lambda x: QColor(*x)
        )

    def getNextPmapColor(self):
        return self._getNext(
            self.topLevelOperatorView.PmapColors,
            super(ObjectClassificationGui, self).getNextPmapColor,
            lambda x: QColor(*x)
        )

    def onLabelNameChanged(self):
        self._onLabelChanged(super(ObjectClassificationGui, self).onLabelNameChanged,
                             lambda l: l.name,
                             self.topLevelOperatorView.LabelNames)

    def onLabelColorChanged(self):
        self._onLabelChanged(super(ObjectClassificationGui, self).onLabelColorChanged,
                             lambda l: (l.brushColor().red(),
                                        l.brushColor().green(),
                                        l.brushColor().blue()),
                             self.topLevelOperatorView.LabelColors)


    def onPmapColorChanged(self):
        self._onLabelChanged(super(ObjectClassificationGui, self).onPmapColorChanged,
                             lambda l: (l.pmapColor().red(),
                                        l.pmapColor().green(),
                                        l.pmapColor().blue()),
                             self.topLevelOperatorView.PmapColors)

    def _onLabelRemoved(self, parent, start, end):
        super(ObjectClassificationGui, self)._onLabelRemoved(parent, start, end)
        op = self.topLevelOperatorView
        op.removeLabel(start)
        for slot in (op.LabelNames, op.LabelColors, op.PmapColors):
            value = slot.value
            if start in value:
                value.pop(start)
            slot.setValue(value)


    def createLabelLayer(self, direct=False):
        """Return a colortable layer that displays the label slot
        data, along with its associated label source.

        direct: whether this layer is drawn synchronously by volumina

        """
        labelInput = self._labelingSlots.labelInput
        labelOutput = self._labelingSlots.labelOutput

        if not labelOutput.ready():
            return (None, None)
        else:
            self._colorTable16[15] = QColor(Qt.black).rgba() #for the objects with NaNs in features


            labelsrc = LazyflowSinkSource(labelOutput,
                                          labelInput)
            labellayer = ColortableLayer(labelsrc,
                                         colorTable=self._colorTable16,
                                         direct=direct)

            labellayer.segmentationImageSlot = self.op.SegmentationImagesOut
            labellayer.name = "Labels"
            labellayer.ref_object = None
            labellayer.zeroIsTransparent  = False
            labellayer.colortableIsRandom = True

            clickInt = ClickInterpreter(self.editor, labellayer,
                                        self.onClick, right=False,
                                        double=False)
            self.editor.brushingInterpreter = clickInt

            return labellayer, labelsrc

    def setupLayers(self):

        # Base class provides the label layer.
        layers = super(ObjectClassificationGui, self).setupLayers()

        binarySlot = self.op.BinaryImages
        segmentedSlot = self.op.SegmentationImages
        rawSlot = self.op.RawImages

        #This is just for colors
        labels = self.labelListData
        
        for channel, probSlot in enumerate(self.op.PredictionProbabilityChannels):
            if probSlot.ready() and channel < len(labels):
                ref_label = labels[channel]
                probsrc = LazyflowSource(probSlot)
                probLayer = AlphaModulatedLayer( probsrc,
                                                 tintColor=ref_label.pmapColor(),
                                                 range=(0.0, 1.0),
                                                 normalize=(0.0, 1.0) )
                probLayer.opacity = 0.25
                #probLayer.visible = self.labelingDrawerUi.checkInteractive.isChecked()
                #False, because it's much faster to draw predictions without these layers below
                probLayer.visible = False
                probLayer.setToolTip("Probability that the object belongs to class {}".format(channel+1))
                    
                def setLayerColor(c, predictLayer=probLayer, ch=channel):
                    predictLayer.tintColor = c

                def setLayerName(n, predictLayer=probLayer):
                    newName = "Prediction for %s" % n
                    predictLayer.name = newName

                setLayerName(ref_label.name)
                ref_label.pmapColorChanged.connect(setLayerColor)
                ref_label.nameChanged.connect(setLayerName)
                layers.append(probLayer)

        predictionSlot = self.op.PredictionImages
        if predictionSlot.ready():
            predictsrc = LazyflowSource(predictionSlot)
            self._colorTable16_forpmaps[0] = 0
            predictLayer = ColortableLayer(predictsrc,
                                           colorTable=self._colorTable16_forpmaps)

            predictLayer.name = "Prediction"
            predictLayer.ref_object = None
            predictLayer.visible = self.labelingDrawerUi.checkInteractive.isChecked()
            predictLayer.opacity = 0.5
            predictLayer.setToolTip("Classification results, assigning a label to each object")
            
            # This weakref stuff is a little more fancy than strictly necessary.
            # The idea is to use the weakref's callback to determine when this layer instance is destroyed by the garbage collector,
            #  and then we disconnect the signal that updates that layer.
            weak_predictLayer = weakref.ref( predictLayer )
            colortable_changed_callback = bind( self._setPredictionColorTable, weak_predictLayer )
            self._labelControlUi.labelListModel.dataChanged.connect( colortable_changed_callback )
            weak_predictLayer2 = weakref.ref( predictLayer, partial(self._disconnect_dataChange_callback, colortable_changed_callback) )
            # We have to make sure the weakref isn't destroyed because it is responsible for calling the callback.
            # Therefore, we retain it by adding it to a list.
            self._retained_weakrefs.append( weak_predictLayer2 )

            # Ensure we're up-to-date (in case this is the first time the prediction layer is being added.
            for row in range( self._labelControlUi.labelListModel.rowCount() ):
                self._setPredictionColorTableForRow( predictLayer, row )

            # put right after Labels, so that it is visible after hitting "live
            # predict".
            layers.insert(1, predictLayer)

        badObjectsSlot = self.op.BadObjectImages
        if badObjectsSlot.ready():
            ct_black = [0, QColor(Qt.black).rgba()]
            badSrc = LazyflowSource(badObjectsSlot)
            badLayer = ColortableLayer(badSrc, colorTable = ct_black)
            badLayer.name = "Ambiguous objects"
            badLayer.setToolTip("Objects with infinite or invalid values in features")
            badLayer.visible = False
            layers.append(badLayer)

        if segmentedSlot.ready():
            ct = colortables.create_default_16bit()
            objectssrc = LazyflowSource(segmentedSlot)
            ct[0] = QColor(0, 0, 0, 0).rgba() # make 0 transparent
            objLayer = ColortableLayer(objectssrc, ct)
            objLayer.name = "Objects"
            objLayer.opacity = 0.5
            objLayer.visible = False
            objLayer.setToolTip("Segmented objects (labeled image/connected components)")
            layers.append(objLayer)

        if binarySlot.ready():
            ct_binary = [0,
                         QColor(255, 255, 255, 255).rgba()]
            
            # white foreground on transparent background, even for labeled images
            binct = [QColor(255, 255, 255, 255).rgba()]*65536
            binct[0] = 0
            binaryimagesrc = LazyflowSource(binarySlot)
            binLayer = ColortableLayer(binaryimagesrc, binct)
            binLayer.name = "Binary image"
            binLayer.visible = True
            binLayer.opacity = 1.0
            binLayer.setToolTip("Segmentation results as a binary mask")
            layers.append(binLayer)

        if rawSlot.ready():
            rawLayer = self.createStandardLayerFromSlot(rawSlot)
            rawLayer.name = "Raw data"
            layers.append(rawLayer)

        # since we start with existing labels, it makes sense to start
        # with the first one selected. This would make more sense in
        # __init__(), but it does not take effect there.
        #self.selectLabel(0)

        return layers

    def _disconnect_dataChange_callback(self, colortable_changed_callback, *args ):
        """
        When instances of the prediction layer are garbage collected, we no longer want the list model to call them back.
        This function disconnects the signal that was connected in setupLayers, above.
        """
        self._labelControlUi.labelListModel.dataChanged.disconnect( colortable_changed_callback )

    def _setPredictionColorTable(self, weak_predictLayer, index1, index2):
        predictLayer = weak_predictLayer()
        if predictLayer is None:
            return
        row = index1.row()
        self._setPredictionColorTableForRow(predictLayer, row)

    def _setPredictionColorTableForRow(self, predictLayer, row):
        if row >= 0 and row < self._labelControlUi.labelListModel.rowCount():
            element = self._labelControlUi.labelListModel[row]
            oldcolor = self._colorTable16_forpmaps[row+1]
            if oldcolor != element.pmapColor().rgba():
                self._colorTable16_forpmaps[row+1] = element.pmapColor().rgba()
                predictLayer.colorTable = self._colorTable16_forpmaps

    @staticmethod
    def _getObject(slot, pos5d):
        slicing = tuple(slice(i, i+1) for i in pos5d)
        arr = slot[slicing].wait()
        return arr.flat[0]

    def onClick(self, layer, pos5d, pos):
        """Extracts the object index that was clicked on and updates
        that object's label.

        """
        label = self.editor.brushingModel.drawnNumber
        if label == self.editor.brushingModel.erasingNumber:
            label = 0

        topLevelOp = self.topLevelOperatorView.viewed_operator()
        imageIndex = topLevelOp.LabelInputs.index( self.topLevelOperatorView.LabelInputs )

        operatorAxisOrder = self.topLevelOperatorView.SegmentationImagesOut.meta.getAxisKeys()
        assert operatorAxisOrder == list('txyzc'), \
            "Need to update onClick() if the operator no longer expects volumina axis order.  Operator wants: {}".format( operatorAxisOrder )
        self.topLevelOperatorView.assignObjectLabel(imageIndex, pos5d, label)

    def handleEditorRightClick(self, position5d, globalWindowCoordinate):
        layer = self.getLayer('Labels')
        obj = self._getObject(layer.segmentationImageSlot, position5d)
        if obj == 0:
            return

        menu = QMenu(self)
        text = "print info for object {} in the terminal".format(obj)
        menu.addAction(text)
        clearlabel = "clear object label"
        menu.addAction(clearlabel)
        numLabels = self.labelListData.rowCount()
        label_actions = []
        for l in range(numLabels):
            color_icon = self.labelListData.createIconForLabel(l)
            act_text = "label with label {}".format(l+1)
            act = QAction(color_icon, act_text, menu)
            act.setIconVisibleInMenu(True)
            label_actions.append(act_text)
            menu.addAction(act)
            
        
        action = menu.exec_(globalWindowCoordinate)
        if action is None:
            return
        if action.text() == text:
            numpy.set_printoptions(precision=4)
            logger.info( "------------------------------------------------------------" )
            logger.info( "object:         {}".format(obj) )
            
            t = position5d[0]
            labels = self.op.LabelInputs([t]).wait()[t]
            if len(labels) > obj:
                label = int(labels[obj])
            else:
                label = "none"
            logger.info( "label:          {}".format(label) )
            
            logger.info( 'features:' )
            feats = self.op.ObjectFeatures([t]).wait()[t]
            selected = self.op.SelectedFeatures([]).wait()
            for plugin in sorted(feats.keys()):
                if plugin == default_features_key or plugin not in selected:
                    continue
                logger.info( "Feature category: {}".format(plugin) )
                for featname in sorted(feats[plugin].keys()):
                    if featname not in selected[plugin]:
                        continue
                    value = feats[plugin][featname]
                    ft = numpy.asarray(value.squeeze())[obj]
                    logger.info( "{}: {}".format(featname, ft) )

            if len(selected)>0 and label!='none':
                if self.op.Predictions.ready():
                    preds = self.op.Predictions([t]).wait()[t]
                    if len(preds) >= obj:
                        pred = int(preds[obj])
                else:
                    pred = 'none'
                
                prob = 'none'
                if self.op.Probabilities.ready():
                    probs = self.op.Probabilities([t]).wait()[t]
                    if len(probs) >= obj:
                        prob = probs[obj]
    
                logger.info( "probabilities:  {}".format(prob) )
                logger.info( "prediction:     {}".format(pred) )

            
            logger.info( "------------------------------------------------------------" )
        elif action.text()==clearlabel:
            topLevelOp = self.topLevelOperatorView.viewed_operator()
            imageIndex = topLevelOp.LabelInputs.index( self.topLevelOperatorView.LabelInputs )
            self.topLevelOperatorView.assignObjectLabel(imageIndex, position5d, 0)
        else:
            try:
                label = label_actions.index(action.text())
            except ValueError:
                return
            topLevelOp = self.topLevelOperatorView.viewed_operator()
            imageIndex = topLevelOp.LabelInputs.index( self.topLevelOperatorView.LabelInputs )
            self.topLevelOperatorView.assignObjectLabel(imageIndex, position5d, label+1)
            
            


    def setVisible(self, visible):
        super(ObjectClassificationGui, self).setVisible(visible)

        if visible:
            subslot_index = self.op.current_view_index()
            if subslot_index == -1:
                return
            temp = self.op.triggerTransferLabels(subslot_index)
        else:
            temp = None
        if temp is not None:
            new_labels, old_labels_lost, new_labels_lost = temp
            labels_lost = dict(old_labels_lost.items() + new_labels_lost.items())
            if sum(len(v) for v in labels_lost.itervalues()) > 0:
                self.warnLost(labels_lost)

    def warnLost(self, labels_lost):
        box = QMessageBox(QMessageBox.Warning,
                          'Warning',
                          'Some of your labels could not be transferred',
                          QMessageBox.NoButton,
                          self)
        messages = {
            'full': "These labels were lost completely:",
            'partial': "These labels were lost partially:",
            'conflict': "These new labels conflicted:"
        }
        default_message = "These labels could not be transferred:"

        _sep = "\t"
        cases = []
        for k, val in labels_lost.iteritems():
            if len(val) > 0:
                msg = messages.get(k, default_message)
                axis = _sep.join(["X", "Y", "Z"])
                coords = "\n".join([_sep.join(["{:<8.1f}".format(i) for i in item])
                                    for item in val])
                cases.append("\n".join([msg, axis, coords]))
        box.setDetailedText("\n\n".join(cases))
        box.show()


    @threadRouted
    def handleWarnings(self, *args, **kwargs):
        # FIXME: dialog should not steal focus
        warning = self.op.Warnings[:].wait()
        try:
            box = self.badObjectBox
        except AttributeError:
            box = QMessageBox(QMessageBox.Warning,
                              warning['title'],
                              warning['text'],
                              QMessageBox.NoButton,
                              self)
            box.setWindowModality(Qt.NonModal)
            box.move(self.geometry().width(), 0)
        box.setWindowTitle(warning['title'])
        box.setText(warning['text'])
        box.setInformativeText(warning.get('info', ''))
        box.setDetailedText(warning.get('details', ''))
        box.show()
        self.badObjectBox = box
