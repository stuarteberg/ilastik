from collections import defaultdict
import cgi

class ObjectFeatureInfo(object):
    def __init__(self, humanName, size, group):
        self.humanName = humanName
        self.group  = group
        self._size = size
        
    def size(self, dim, ch):
        if ch == 0:
            ch = 1
        if isinstance(self._size, int):
            return self._size
        if self._size == "coor":
            return 2 if dim == 2 else 3
        if self._size == "coor2":
            return 4 if dim == 2 else 9
        elif self._size == "ch":
            return ch
        elif self._size == "ch2":
            return ch*ch
        

r = { \
"Coord<ArgMaxWeight >"                                       : ObjectFeatureInfo("Coordinate of pixel with maximal intensity" ,"coor",   "coordinates"),
"Coord<ArgMinWeight >"                                       : ObjectFeatureInfo("Coordinate of pixel with minimal intensity" ,"coor",   "coordinates"),
"Coord<Maximum >"                                            : ObjectFeatureInfo("Lower right coordinate of bounding box"     ,"coor",   "coordinates"),
"Coord<Minimum >"                                            : ObjectFeatureInfo("Upper left coordinate of bounding box"      ,"coor",   "coordinates"),
"Count"                                                      : ObjectFeatureInfo("Pixel count"                                ,1,   "shape"),
"Global<Maximum >"                                           : ObjectFeatureInfo("Maximal intensity (search entire image)"    ,1,   "global"),
"Global<Minimum >"                                           : ObjectFeatureInfo("Minimal intensity (search entire image)"    ,1,   "global"),
"Histogram"                                                  : ObjectFeatureInfo("Intensity Histogram"                        ,64,   "intensity"),
"Kurtosis"                                                   : ObjectFeatureInfo("Kurtosis (4th moment) of intensities"       ,1,   "intensity"),
"Maximum"                                                    : ObjectFeatureInfo("Maximal intensity"                          ,"ch",   "intensity"),
"Minimum"                                                    : ObjectFeatureInfo("Minimal intensity"                          ,"ch",   "intensity"),
"Mean"                                                       : ObjectFeatureInfo("Mean intensity"                             ,"ch",   "intensity"),
"Quantiles"                                                  : ObjectFeatureInfo("Quantiles (0%, 10%, 25%, 50%, 75%, 90%, 100%) of intensities", 7, "intensity"),
"RegionAxes"                                                 : ObjectFeatureInfo("Eigenvectors from PCA (each pixel has unit mass)", "coor2", "shape",),
"RegionCenter"                                               : ObjectFeatureInfo("Center of mass (each pixel has unit mass)", "coor", "coordinates"),
"RegionRadii"                                                : ObjectFeatureInfo("Eigenvalues from PCA (each pixel has unit mass)", "coor", "shape"),
"Skewness"                                                   : ObjectFeatureInfo("Skewness (3rd moment) of intensities", "ch", "intensity"),
"Sum"                                                        : ObjectFeatureInfo("Sum of pixel intensities", "ch", "intensity"),
"Variance"                                                   : ObjectFeatureInfo("Variance (2nd moment) of intensities", "ch", "intensity"),
"Covariance"                                                 : ObjectFeatureInfo("Covariance", "ch2", "intensity"),
"Weighted<RegionAxes>"                                       : ObjectFeatureInfo("Eigenvectors from PCA (each pixel has mass according to intensity)", "coor2", "shape"),
"Weighted<RegionCenter>"                                     : ObjectFeatureInfo("Center of mass (each pixel has mass according to its intensity)", "coor", "shape"),
"Weighted<RegionRadii>"                                      : ObjectFeatureInfo("Eigenvalues from PCA (each pixel has mass according to intensity)", "coor", "shape"),
"Central<PowerSum<2> >"                                      : ObjectFeatureInfo("",0, "unused"),
"Central<PowerSum<3> >"                                      : ObjectFeatureInfo("",0, "unused"),
"Central<PowerSum<4> >"                                      : ObjectFeatureInfo("",0, "unused"),
"Coord<DivideByCount<Principal<PowerSum<2> > > >"            : ObjectFeatureInfo("",0, "unused"),
"Coord<PowerSum<1> >"                                        : ObjectFeatureInfo("",0, "unused"),
"Coord<Principal<Kurtosis > >"                               : ObjectFeatureInfo("",0, "unused"),
"Coord<Principal<PowerSum<2> > >"                            : ObjectFeatureInfo("",0, "unused"),
"Coord<Principal<PowerSum<3> > >"                            : ObjectFeatureInfo("",0, "unused"),
"Coord<Principal<PowerSum<4> > >"                            : ObjectFeatureInfo("",0, "unused"),
"Coord<Principal<Skewness > >"                               : ObjectFeatureInfo("",0, "unused"),
"Weighted<Coord<DivideByCount<Principal<PowerSum<2> > > > >" : ObjectFeatureInfo("",0, "unused"),
"Weighted<Coord<PowerSum<1> > >"                             : ObjectFeatureInfo("",0, "unused"),
"Weighted<Coord<Principal<Kurtosis > > >"                    : ObjectFeatureInfo("",0, "unused"),
"Weighted<Coord<Principal<PowerSum<2> > > >"                 : ObjectFeatureInfo("",0, "unused"),
"Weighted<Coord<Principal<PowerSum<3> > > >"                 : ObjectFeatureInfo("",0, "unused"),
"Weighted<Coord<Principal<PowerSum<4> > > >"                 : ObjectFeatureInfo("",0, "unused"),
"Weighted<Coord<Principal<Skewness > > >"                    : ObjectFeatureInfo("",0, "unused"),
"Weighted<PowerSum<0> >"                                     : ObjectFeatureInfo("",0, "unused"),
"Principal<Maximum >": ObjectFeatureInfo("",0, "unused"),
"Principal<Kurtosis >": ObjectFeatureInfo("",0, "unused"),
"Principal<Minimum >": ObjectFeatureInfo("",0, "unused"),
"Principal<PowerSum<2> >": ObjectFeatureInfo("",0, "unused"),
"Principal<PowerSum<3> >": ObjectFeatureInfo("",0, "unused"),
"Principal<PowerSum<4> >": ObjectFeatureInfo("",0, "unused"),
"Principal<Skewness >": ObjectFeatureInfo("",0, "unused"),
"Principal<Variance>": ObjectFeatureInfo("",0, "unused"),
"PrincipalAxes": ObjectFeatureInfo("",0, "unused"),
}

import vigra, numpy

def testObjectFeatureDefinitions():
    shapes = [
        (30,40,50),
        (30,40),
    ]

    for channel in [0, 2, 3, 4]:
        for shape in shapes:
            if channel == 0:
                data = numpy.random.random(shape).astype(numpy.float32)
            else:
                data = numpy.random.random(shape+(channel,)).astype(numpy.float32)
            seg  = numpy.zeros(shape, dtype=numpy.uint32)
            seg.flat = numpy.arange(1,numpy.prod(seg.shape)+1)
            
            features = vigra.analysis.extractRegionFeatures(data, seg, features="all")
            #import IPython; IPython.embed()
            
            for k in features.keys():
                if k == "Kurtosis" or k == "Principal<Kurtosis >":
                    continue
                
                print k
                assert k in r, "feature %s not available for shape=%r, channel=%d" % (k, shape, channel)
                info = r[k]
                
                print "%%%%",k
                feat = features[k]
                if info.humanName == "":
                    continue
                
                realSize = numpy.prod(feat.shape[1:]) if isinstance(feat, numpy.ndarray) and len(feat.shape) > 1 else 1
                assert info.size(len(shape), channel) == realSize, "%s has real size %d, but needs %d (shape=%r, channels=%d)" % (k, realSize, info.size(len(shape), channel), shape, channel)
                    
            grouped = defaultdict(list)
            from itertools import groupby
            for key, group in groupby(r, lambda x: r[x].group):
                for thing in group:
                    grouped[key].append(thing) 
                    
            for k,vv in grouped.iteritems():
                print "*** %s ***" % k
                for v in vv:
                    print "    %s" % r[v].humanName
            
from PyQt4.QtGui import *
from PyQt4.QtCore import *
app = QApplication([])

class ObjectFeatureSelectionWidget(QWidget):
    
    msg_NoFeatureSelected = "No feature selected"
    msg_FeaturesSelected  = "%d features selected, %d channels in total"
    
    def __init__(self, dim, channels, parent=None):
        super(ObjectFeatureSelectionWidget, self).__init__(parent)
        
        self.dim        = dim
        self.channels   = channels
        self.treeWidget = None
        self.label      = None
        self.item2id    = {}
        self.help       = QTextBrowser(self)

        self.treeWidget = QTreeWidget()
        self.treeWidget.header().close()
        pluginRoot = QTreeWidgetItem()
        pluginRoot.setText(0, "the plugin")
        self.treeWidget.insertTopLevelItem(0, pluginRoot)
        self.label = QLabel(self)
        self.label.setText(self.msg_NoFeatureSelected)
        
        v = QVBoxLayout()
        v.addWidget(self.treeWidget)
        v.addWidget(self.label)
        
        h = QSplitter(self)
        w = QWidget(self)
        w.setLayout(v)
        h.addWidget(w)
        h.addWidget(self.help)
        
        v2 = QHBoxLayout()
        v2.addWidget(h)
        self.setLayout(v2)
        
        grouped = defaultdict(list)
        from itertools import groupby
        for key, group in groupby(r, lambda x: r[x].group):
            for thing in group:
                grouped[key].append(thing) 
        
        for k,vv in grouped.iteritems():
            if k == "unused":
                continue
            groupRoot = QTreeWidgetItem()
            groupRoot.setText(0, k)
            pluginRoot.addChild(groupRoot)
            groupRoot.setExpanded(True)
            for v in vv:
                child = QTreeWidgetItem()
                child.setText(0, r[v].humanName)
                self.item2id[child] = v
                groupRoot.addChild(child)
                child.setCheckState(0, Qt.Unchecked)
        
        pluginRoot.setExpanded(True)
        self.treeWidget.itemChanged.connect(self.handle)
        self.treeWidget.itemSelectionChanged.connect(self.handleSelectionChanged)

    def handleSelectionChanged(self):
        sel = self.treeWidget.selectedItems()
        assert len(sel) <= 1
        if not len(sel) or sel[0] not in self.item2id:
            self.help.setText("")
            return
        
        sel = sel[0]
        info = r[self.item2id[sel]]
        self.help.setText("<h2>%s</h2><p>vigra function: <tt>%s</tt></p><p>#channels: %d</p>" \
            % (info.humanName, cgi.escape(self.item2id[sel]), info.size(self.dim, self.channels)))
        
        

    def handleChecked(self, checked, item, column):
        print self.item2id[item], checked
        
        vigraName = self.item2id[item]
      
        nCh = 0
        nFeat = 0
        for item, vigraName in self.item2id.iteritems():
            if not item.checkState(0) == Qt.Checked:
                continue
            nCh += r[vigraName].size(self.dim, self.channels)
            nFeat += 1
            
        if nFeat == 0:
            self.label.setText(self.msg_NoFeatureSelected)
        else:
            self.label.setText(self.msg_FeaturesSelected % (nFeat, nCh))
    
    def handle(self, item, column):
        self.treeWidget.blockSignals(True)
        if item.checkState(column) == Qt.Checked:
            self.handleChecked(True, item, column)
        elif item.checkState(column) == Qt.Unchecked:
            self.handleChecked(False, item, column)
        self.treeWidget.blockSignals(False)
        
    def selectedFeatures(self):
        sel = []
        for item, vigraName in self.item2id.iteritems():
            if not item.checkState(0) == Qt.Checked:
                continue
            sel.append(vigraName)
        return sorted(sel)
           
t = ObjectFeatureSelectionWidget(2, 0)
t.show()
app.exec_()
