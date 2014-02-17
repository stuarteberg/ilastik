import os
import h5py
import numpy
import vigra
import unittest
import shutil
import tempfile
from lazyflow.graph import Graph, Operator, InputSlot, Slot, OperatorWrapper
from lazyflow.operators import OpTrainRandomForestBlocked, OpValueCache, OpBlockedSparseLabelArray

from ilastik.applets.base.appletSerializer import \
    SerialSlot, SerialListSlot, AppletSerializer, SerialDictSlot, SerialBlockSlot

class OpMock(Operator):
    """A simple operator for testing serializers."""
    name = "OpMock"
    TestSlot = InputSlot(name="TestSlot")
    TestMultiSlot = InputSlot(name="TestMultiSlot", level=1)
    TestListSlot = InputSlot(name='TestListSlot')

    def __init__(self, *args, **kwargs):
        super(OpMock, self).__init__(*args, **kwargs)

    def propagateDirty(self, slot, subindex, roi):
        pass


class OpMockSerializer(AppletSerializer):
    def __init__(self, operator, groupName):
        self.TestSerialSlot = SerialSlot(operator.TestSlot)
        self.TestMultiSerialSlot = SerialSlot(operator.TestMultiSlot)
        self.TestSerialListSlot = SerialListSlot(operator.TestListSlot,
                                                 selfdepends=True)
        slots = (self.TestSerialSlot,
                 self.TestMultiSerialSlot,
                 self.TestSerialListSlot)
        super(OpMockSerializer, self).__init__(groupName,
                                               slots)


def randArray():
    return numpy.random.randn(10, 10)


class TestSerializer(unittest.TestCase):
    def setUp(self):
        g = Graph()
        self.operator = OpMock(graph=g)
        self.serializer = OpMockSerializer(self.operator, "TestApplet")
        self.tmpDir = tempfile.mkdtemp()
        self.projectFilePath = os.path.join(self.tmpDir, "tmp_project.ilp")
        self.projectFile = h5py.File(self.projectFilePath)
        self.projectFile.create_dataset("ilastikVersion", data='1.0.0')

    def tearDown(self):
        self.projectFile.close()
        shutil.rmtree(self.tmpDir)

    def _testSlot(self, slot, ss, value, rvalue):
        """test whether serialzing and then deserializing works for a
        level-0 slot

        """
        slot.setValue(value)
        self.assertTrue(ss.dirty)
        self.serializer.serializeToHdf5(self.projectFile, self.projectFilePath)
        self.assertTrue(not ss.dirty)

        slot.setValue(rvalue)
        self.assertTrue(ss.dirty)
        self.assertTrue(numpy.any(slot.value != value))

        self.serializer.deserializeFromHdf5(self.projectFile, self.projectFilePath)
        self.assertTrue(numpy.all(slot.value == value))
        self.assertTrue(not ss.dirty)

    def _testMultiSlot(self, mslot, mss, values, rvalues):
        """test whether serialzing and then deserializing works for a
        level-1 slot

        """
        mslot.resize(len(values))
        for subslot, value in zip(mslot, values):
            subslot.setValue(value)
        if len(mslot) > 0:
            self.assertTrue(mss.dirty)
        self.serializer.serializeToHdf5(self.projectFile, self.projectFilePath)
        if len(mslot) > 0:
            self.assertFalse(mss.dirty)

        mslot.resize(len(rvalues))
        for subslot, value in zip(mslot, rvalues):
            subslot.setValue(value)
        if len(mslot) > 0:
            self.assertTrue(mss.dirty)

        for subslot, value in zip(mslot, values):
            self.assertTrue(numpy.any(subslot.value != value))

        self.serializer.deserializeFromHdf5(self.projectFile, self.projectFilePath)
        for subslot, value in zip(mslot, values):
            self.assertTrue(numpy.all(subslot.value == value))

        # If the multi-slot started with MORE subslots than were stored in the project file,
        #  the extra subslots are NOT removed.  Instead, they are simply disconnected.
        # Verify that the the number of ready() slots matches the number we attempted to save.
        ready_subslots = filter(Slot.ready, mss.slot)
        self.assertEquals(len(ready_subslots), len(values))

        self.assertFalse(mss.dirty)

    def _testList(self, slot, ss, value, rvalue):
        """test whether serialzing and then deserializing works for a
        list slot.

        """
        slot.setValue(value)
        self.assertTrue(ss.dirty)
        self.serializer.serializeToHdf5(self.projectFile, self.projectFilePath)
        self.assertTrue(not ss.dirty)

        slot.setValue(rvalue)
        self.assertTrue(ss.dirty)
        self.assertTrue(slot.value != value)

        self.serializer.deserializeFromHdf5(self.projectFile, self.projectFilePath)
        self.assertTrue(slot.value == value)
        self.assertTrue(not ss.dirty)

    def testSlot(self):
        slot = self.operator.TestSlot
        ss = self.serializer.TestSerialSlot
        self._testSlot(slot, ss, randArray(), randArray())

    def testMultiSlot10(self):
        slot = self.operator.TestMultiSlot
        ss = self.serializer.TestMultiSerialSlot
        self._testMultiSlot(slot, ss, [randArray()], [])

    def testMultiSlot01(self):
        slot = self.operator.TestMultiSlot
        ss = self.serializer.TestMultiSerialSlot

        # FIXME: test fails because multislot is not set to length 0
        # upon deserialization.

        # self._testMultiSlot(slot, ss, [], [randArray()])

    def testMultiSlot11(self):
        slot = self.operator.TestMultiSlot
        ss = self.serializer.TestMultiSerialSlot
        self._testMultiSlot(slot, ss, [randArray()], [randArray()])

    def testMultiSlot22(self):
        slot = self.operator.TestMultiSlot
        ss = self.serializer.TestMultiSerialSlot
        self._testMultiSlot(slot, ss,
                            [randArray(), randArray()],
                            [randArray(), randArray()],)

    def testMultiSlot12(self):
        slot = self.operator.TestMultiSlot
        ss = self.serializer.TestMultiSerialSlot
        self._testMultiSlot(slot, ss,
                            [randArray()],
                            [randArray(), randArray()],)

    def testMultiSlot21(self):
        slot = self.operator.TestMultiSlot
        ss = self.serializer.TestMultiSerialSlot
        self._testMultiSlot(slot, ss,
                            [randArray(), randArray()],
                            [randArray()],)

    def testList01(self):
        slot = self.operator.TestListSlot
        ss = self.serializer.TestSerialListSlot
        self._testList(slot, ss, [], [1, 2, 3])

    def testList10(self):
        slot = self.operator.TestListSlot
        ss = self.serializer.TestSerialListSlot
        self._testList(slot, ss, [4, 5, 6], [])

    def testList11(self):
        slot = self.operator.TestListSlot
        ss = self.serializer.TestSerialListSlot
        self._testList(slot, ss, [7, 8, 9], [10, 11, 12])

class TestSerialDictSlot(unittest.TestCase):
    
    class OpWithDictSlot(Operator):
        InputDict = InputSlot()

        def setupOutputs(self):
            pass
        
        def execute(self, *args, **kwargs):
            pass
        
        def propagateDirty(self, *args, **kwargs):
            pass
    
    class SerializerForOpWithDictSlot(AppletSerializer):
        def __init__(self, operator, groupName):
            self.ss = SerialDictSlot( operator.InputDict )
            super(TestSerialDictSlot.SerializerForOpWithDictSlot, self).__init__(groupName, [self.ss])
        
    
    def setUp(self):
        g = Graph()
        self.operator = self.OpWithDictSlot(graph=g)
        self.serializer = self.SerializerForOpWithDictSlot(self.operator, "TestApplet")
        self.tmpDir = tempfile.mkdtemp()
        self.projectFilePath = os.path.join(self.tmpDir, "tmp_project.ilp")
        self.projectFile = h5py.File(self.projectFilePath)
        self.projectFile.create_dataset("ilastikVersion", data=0.6)

    def tearDown(self):
        self.projectFile.close()
        shutil.rmtree(self.tmpDir)

    def testBasic(self):
        op = self.operator
        ss = self.serializer.ss
        d = {'a' : 'A', 'b' : 'B'}
        op.InputDict.setValue( d )
        
        self.assertTrue( ss.dirty )
        self.serializer.serializeToHdf5(self.projectFile, self.projectFilePath)
        self.assertFalse( ss.dirty )

        # Verify that the values are read back.
        d.clear()
        self.serializer.deserializeFromHdf5(self.projectFile, self.projectFilePath)
        d_read = op.InputDict.value
        self.assertTrue( d_read['a'] == 'A' )
        self.assertTrue( d_read['b'] == 'B' )

        d2 = {'a' : 'A', 'b' : 'B', 'c' : 'C'}
        op.InputDict.setValue( d2 )

        self.assertTrue( ss.dirty )
        self.serializer.serializeToHdf5(self.projectFile, self.projectFilePath)
        self.assertFalse( ss.dirty )
        
        # Verify that the values are read back.
        del d2['b'] # Touch the dict so we know the values are really being read from the file.
        #d2.clear()
        self.assertTrue( len(op.InputDict.value) == 2 )
        self.serializer.deserializeFromHdf5(self.projectFile, self.projectFilePath)
        d2_read = op.InputDict.value
        self.assertTrue( d2_read['a'] == 'A' )
        self.assertTrue( d2_read['b'] == 'B' )
        self.assertTrue( d2_read['c'] == 'C' )

class TestSerialBlockSlot(unittest.TestCase):
    
    def _init_objects(self):
        raw_data = numpy.zeros((100,100,100), dtype=numpy.uint32)
        raw_data = vigra.taggedView(raw_data, 'zyx')
    
        opLabelArrays = OperatorWrapper( OpBlockedSparseLabelArray, graph=Graph() )
        opLabelArrays.Input.resize(1)
        opLabelArrays.Input[0].setValue( raw_data )
        opLabelArrays.shape.setValue( raw_data.shape )
        opLabelArrays.eraser.setValue( 255 )
        opLabelArrays.deleteLabel.setValue( -1 )
        opLabelArrays.blockShape.setValue( (10,10,10) )
        
        # This will serialize/deserialize data to the h5 file.
        slotSerializer = SerialBlockSlot( opLabelArrays.Output, opLabelArrays.Input, opLabelArrays.nonzeroBlocks )
        return opLabelArrays, slotSerializer

    def testBasic(self):
        h5_filepath = os.path.join( tempfile.mkdtemp(), 'serial_blockslot_test.h5' )

        # Create an operator and a serializer to write the data.
        opLabelArrays, slotSerializer = self._init_objects()
    
        # Give it some data.
        opLabelArrays.Input[0][10:11, 10:20, 10:20] = 1*numpy.ones((1,10,10), dtype=numpy.uint8)
        opLabelArrays.Input[0][11:12, 10:20, 10:20] = 2*numpy.ones((1,10,10), dtype=numpy.uint8)
        
        with h5py.File(h5_filepath, 'w') as f:
            label_group = f.create_group('label_data')
            slotSerializer.serialize( label_group )
    
        # Now start again with fresh objects.
        # This time we'll read the data.
        opLabelArrays, slotSerializer = self._init_objects()
    
        with h5py.File(h5_filepath, 'r') as f:
            label_group = f['label_data']
            slotSerializer.deserialize( label_group )

        # Verify that we get the same data back.
        assert ( opLabelArrays.Output[0][10:11, 10:20, 10:20].wait() == 1 ).all()
        assert ( opLabelArrays.Output[0][11:12, 10:20, 10:20].wait() == 2 ).all()

if __name__ == "__main__":
    unittest.main()