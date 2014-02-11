from abc import abstractproperty, abstractmethod
from lazyflow.graph import Operator, Graph
from string import ascii_uppercase
from ilastik.shell.shellAbc import ShellABC

class Workflow( Operator ):
    """
    Base class for all workflows.
    """
    name = "Workflow (base class)"

    ###############################
    # Abstract methods/properties #
    ###############################
    
    @abstractproperty
    def applets(self):
        """
        Abstract property. Return the list of applets that are owned by this workflow.
        """
        return []

    @abstractproperty
    def imageNameListSlot(self):
        """
        Abstract property.  Return the "image name list" slot, which lists the names of 
        all image lanes (i.e. files) currently loaded by the workflow.
        This slot is typically provided by the DataSelection applet via its ImageName slot.
        """
        return None
    
    @property
    def workflowName(self):
        originalName = self.__class__.__name__
        wname = originalName[0]
        for i in originalName[1:]:
            if i in ascii_uppercase:
                wname+=" "
            wname+=i
        if wname.endswith(" Workflow"):
            wname = wname[:-9]
        return wname
    
    @property
    def workflowDescription(self):
        return None
    
    @property
    def defaultAppletIndex(self):
        return 0
    
    @abstractmethod
    def connectLane(self, laneIndex):
        """
        When a new image lane has been added to the workflow, this workflow base class does the following:
        
        1) Create room for the new image lane by adding a lane to each applet's topLevelOperator
        2) Ask the subclass to hook up the new image lane by calling this function.
        """
        raise NotImplementedError
    
    def onProjectLoaded(self, projectManager):
        """
        Called by the project manager after the project is loaded (deserialized).
        Extra workflow initialization be done here.
        """
        pass
    
    def handleAppletStateUpdateRequested(self):
        """
        Called when an applet has fired the :py:attr:`Applet.statusUpdateSignal`
        Workflow subclasses should reimplement this method to enable/disable applet gui's 
        """
        pass

    ##################
    # Public methods #
    ##################

    def __init__(self, shell, headless=False, workflow_cmdline_args=(), parent=None, graph=None):
        """
        Constructor.  Subclasses MUST call this in their own ``__init__`` functions.
        The parent and graph parameters will be passed directly to the Operator base class. If both are None,
        a new Graph is instantiated internally. 
        
        :param headless: Set to True if this workflow is being instantiated by a "headless" script, 
                         in which case the workflow should not attempt to access applet GUIs.
        :param workflow_cmdline_args: a (possibly empty) sequence of arguments to control
                                      the workflow from the command line
        :param parent: The parent operator of the workflow or None (see also: Operator)
        :param graph: The graph instance the workflow is assigned to (see also: Operator)

        """
        
        assert isinstance(shell, ShellABC), \
            "Expected an instance of IlastikShell or HeadlessShell.  Got {}".format( shell )
        if not(parent or graph):
            graph = Graph()
        super(Workflow, self).__init__(parent=parent, graph=graph)
        self._shell = shell
        self._headless = headless

    def cleanUp(self):
        """
        The user closed the project, so this workflow is being destroyed.  
        Tell the applet GUIs to stop processing data, and free any resources that are owned by this workflow or its applets.
        """
        if not self._headless:
            # Stop and clean up the GUIs before we invalidate the operators they depend on.
            for a in self.applets:
                a.getMultiLaneGui().stopAndCleanUp()
        
        # Clean up the graph as usual.
        super(Workflow, self).cleanUp()

    @classmethod
    def getSubclass(cls, name):
        for subcls in cls.all_subclasses:
            if subcls.__name__ == name:
                return subcls
        raise RuntimeError("No known workflow class has name " + name)

    ###################
    # Private methods #
    ###################

    def _after_init(self):
        """
        Overridden from Operator.
        """
        Operator._after_init(self)

        # When a new image is added to the workflow, each applet should get a new lane.
        self.imageNameListSlot.notifyInserted( self._createNewImageLane )
        self.imageNameListSlot.notifyRemove( self._removeImageLane )
        
        for applet in self.applets:
            applet.appletStateUpdateRequested.connect( self.handleAppletStateUpdateRequested )
        
    def _createNewImageLane(self, multislot, index, *args):
        """
        A new image lane is being added to the workflow.  Add a new lane to each applet and hook it up.
        """
        from lazyflow.utility import Timer

        with Timer() as lane_timer:
            for applet_index, a in enumerate(self.applets):
                if a.syncWithImageIndex and a.topLevelOperator is not None:
                    with Timer() as applet_timer:
                        a.topLevelOperator.addLane(index)
                    print "    Adding lane {} to applet {} took {:.3f} seconds"\
                          "".format( index, applet_index, applet_timer.seconds() )

            with Timer() as connection_timer:
                self.connectLane(index)
            print "  Connecting lane {} took {:.3f} seconds".format( index, connection_timer.seconds() )
    
            if not self._headless:
                for a in self.applets:
                    a.getMultiLaneGui().imageLaneAdded(index)
        print "Setup of lane {} took a total of {:.3f} seconds".format( index, lane_timer.seconds() )
    
    def _removeImageLane(self, multislot, index, finalLength):
        """
        An image lane is being removed from the workflow.  Remove it from each of the applets.
        """
        if not self._headless:
            for a in self.applets:
                a.getMultiLaneGui().imageLaneRemoved(index, finalLength)

        for a in self.applets:
            if a.syncWithImageIndex and a.topLevelOperator is not None:
                a.topLevelOperator.removeLane(index, finalLength)

def all_subclasses(cls):
    return cls.__subclasses__() + [g for s in cls.__subclasses__()
                                   for g in all_subclasses(s)]

def getAvailableWorkflows():
    '''iterate over all workflows that were imported'''
    alreadyListed = set()

    for W in all_subclasses(Workflow):
        if W.__name__ in alreadyListed:
            continue
        alreadyListed.add(W.__name__)

        # this is a hack to ensure the base object workflow does not
        # appear in the list of available workflows.
        try:
            isbase = 'base' in W.workflowName.lower()
        except:
            isbase = False
        if isbase:
            continue

        if isinstance(W.workflowName, str):
            yield W, W.workflowName
        else:
            originalName = W.__name__
            wname = originalName[0]
            for i in originalName[1:]:
                if i in ascii_uppercase:
                    wname+=" "
                wname += i
            if wname.endswith(" Workflow"):
                wname = wname[:-9]
            yield W, wname

def getWorkflowFromName(Name):
    '''return workflow by naming its workflowName variable'''
    for w,_name in getAvailableWorkflows():
        if _name==Name or w.__name__==Name:
            return w
