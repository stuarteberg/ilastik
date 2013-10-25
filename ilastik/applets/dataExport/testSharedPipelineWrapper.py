import numpy

from lazyflow.graph import Graph, Operator, InputSlot, OutputSlot

from sharedPipelineWrapper import SharedPipelineWrapper

class OpSamplePipeline( Operator ):
    Input = InputSlot()
    Multiplier = InputSlot()

    Output = OutputSlot()
    
    def __init__(self, *args, **kwargs):
        super( OpSamplePipeline, self ).__init__( *args, **kwargs )

    def setupOutputs(self):
        self.Output.meta.assignFrom(self.Input.meta)
        drange = self.Input.meta.drange
        if drange:
            multiplier = self.Multiplier.value
            output_drange = (drange[0] * multiplier, drange[1] * multiplier)
            self.Output.meta.drange = output_drange
        
    
    def execute(self, slot, subindex, roi, result):
        self.Input(roi.start, roi.stop).writeInto(result).wait()
        result[:] *= self.Multiplier.value
        return result
    
    def propagateDirty(self, slot, subindex, roi):
        self.Output.setDirty(roi)
    
    def setInSlot(self, slot, subindex, key, value):
        pass


class TestSharedPipelineWrapper(object):
    
    def test(self):
        graph = Graph()
        opPipeline = OpSamplePipeline( graph=graph )
        
        wrapper = SharedPipelineWrapper( opPipeline, ['Multiplier'], graph=graph )
        assert 'Input' in wrapper.inputs
        assert 'Multiplier' in wrapper.inputs
        assert 'Output' in wrapper.outputs

        assert wrapper.Multiplier.level == 0
        assert wrapper.Input.level == 1
        assert wrapper.Output.level == 1

        assert len( wrapper.Input ) == 0
        assert len( wrapper.Output ) == 0

        MULTIPLIER = 100
        wrapper.Multiplier.setValue( MULTIPLIER )
        
        # Try a resize
        NUM_SLOTS = 10
        wrapper.Input.resize( NUM_SLOTS )
        input_data = numpy.random.random( (100,100) ).astype(numpy.float32)

        for slot in wrapper.Input:
            slot.setValue( input_data )
        
        for index in range(NUM_SLOTS):
            assert not wrapper.Output[index].ready()

        wrapper.SelectedIndex.setValue(0)

        def _check_ready_states():            
            for index in range(NUM_SLOTS):
                expected_readiness = ( index == wrapper.SelectedIndex.value )
                assert wrapper.Output[index].ready() == expected_readiness, \
                    "wrapper.Output[{}].ready() == {}, should be {}".format( index, wrapper.Output[index].ready(), expected_readiness )

        _check_ready_states()

        result = wrapper.Output[0][:].wait()
        assert ( result == MULTIPLIER * input_data ).all()

        wrapper.SelectedIndex.setValue(5)
        _check_ready_states()

if __name__ == "__main__":
    import sys
    import nose
    sys.argv.append("--nocapture")    # Don't steal stdout.  Show it on the console as usual.
    sys.argv.append("--nologcapture") # Don't set the logging level to DEBUG.  Leave it alone.
    nose.run(defaultTest=__file__)
