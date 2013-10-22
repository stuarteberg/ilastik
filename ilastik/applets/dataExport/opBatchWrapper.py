from lazyflow.graph import Operator, InputSlot

class SharedPipelineWrapper(Operator):
    
    SelectedIndex = InputSlot()
    
    def __init__(self, parent, pipelineInstance, broadcastingSlotNames):
        super( SharedPipelineWrapper, self ).__init__( parent=parent )

        self._pipelineInstance = pipelineInstance
        self._selected_index = -1

        # Create an input slot for each input in the pipeline.
        # The non-broadcasted slots are 'up-leveled'.
        for name, innerSlot in sorted(pipelineInstance.inputs.items(),
                                      key=lambda (k,v): v._global_slot_id):
            level = innerSlot.level
            if innerSlot.name not in broadcastingSlotNames:
                level += 1
            outerSlot = innerSlot._getInstance(self, level=level)
            self.inputs[outerSlot.name] = outerSlot
            setattr(self, outerSlot.name, outerSlot)

        # Create an output slot for each output in the pipeline.
        # All slots are 'up-leveled'
        for name, innerSlot in sorted(pipelineInstance.outputs.items(),
                                      key=lambda (k,v): v._global_slot_id):
            level = innerSlot.level + 1
            outerSlot = innerSlot._getInstance(self, level=level)
            self.outputs[outerSlot.name] = outerSlot
            setattr(self, outerSlot.name, outerSlot)

        broadcastingSlots = map( lambda slot: slot.name in broadcastingSlotNames,
                                 self.inputs.values() )
        self._indexedInputSlots = list( set(broadcastingSlots) - set(self.inputs.values()) )

        # register callbacks for inserted and removed input subslots
        for s in self.inputs.values():
            if s.name in self.promotedSlotNames:
                s.notifyInserted(self._callbackInserted)
                s.notifyRemove(self._callbackPreRemove)
                s.notifyRemoved(self._callbackPostRemoved)
                s._notifyConnect(self._callbackConnect)

        # register callbacks for inserted and removed output subslots
        for s in self.outputs.values():
            s.notifyInserted(self._callbackInserted)
            s.notifyRemove(self._callbackPreRemove)
            s.notifyRemoved(self._callbackPostRemoved)

        for s in self.inputs.values():
            assert len(s) == 0
        for s in self.outputs.values():
            assert len(s) == 0

    def _callbackInserted(self, slot, index, size):
        pass

    def _callbackPreRemove(self, slot, index, length):
        # TODO: If the currently selected slot is removed, switch to a different connection first.
        pass

    def _callbackPostRemoved(self, slot, index, size):
        pass

    def _callbackConnect(self, slot):
        pass

    def handleEarlyDisconnect(self, slot):
        assert False, \
            ("You aren't allowed to disconnect the internal"
             " connections of an operator wrapper.")

    def setupOutputs(self):
        selected_index = self.SelectedIndex.value
        if self._selected_index == selected_index:
            return

        old_selected_index = self._selected_index
        self._selected_index = selected_index

        # Connect selected output subslots to the inner pipeline
        for outerSlot in self.outputs.values():
            innerSlot = self._pipelineInstance.outputs[outerSlot.name]
            if self._selected_index != -1:
                outerSlot[old_selected_index].disconnect()
            outerSlot[selected_index].connect( innerSlot )

        # Connect inner pipeline to the selected input subslots
        for outerSlot in self._indexedInputSlots:
            innerSlot = self._pipelineInstance.inputs[outerSlot.name]
            innerSlot.disconnect()
            innerSlot.connect( outerSlot[selected_index] )
        
        # TODO: For all unconnected outputs, provide default/fake metadata?

    def execute(self, slot, subindex, roi, result):
        #this should never be called !!!
        assert False, \
            "SharedPipelineWrapper execute() function should never be called.  "\
            "You can only ask for data from SUBslots, not the outer multi-slots themselves."

    def setInSlot(self, slot, subindex, key, value):
        if slot in self._indexedInputSlots:
            assert subindex[0] == self._selected_index, \
                "Not allowed to inject data into this input slot.  "\
                "It is not currently connected to the inner pipeline."

    def propagateDirty(self, slot, subindex, roi):
        # Nothing to do: All inputs are directly connected to internal
        # operators.
        pass
