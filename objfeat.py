from collections import defaultdict

class ObjectFeatureInfo(object):
    def __init__(self, humanName, size2D, size3D, group):
        self.humanName = humanName
        self.size2D = size2D
        self.size3D = size3D
        self.group  = group

r = { \
"Coord<ArgMaxWeight >"                                       : ObjectFeatureInfo("Coordinate of pixel with maximal intensity" ,2,3,   "coordinates"),
"Coord<ArgMinWeight >"                                       : ObjectFeatureInfo("Coordinate of pixel with minimal intensity" ,2,3,   "coordinates"),
"Coord<Maximum >"                                            : ObjectFeatureInfo("Lower right coordinate of bounding box"     ,2,3,   "coordinates"),
"Coord<Minimum >"                                            : ObjectFeatureInfo("Upper left coordinate of bounding box"      ,2,3,   "coordinates"),
"Count"                                                      : ObjectFeatureInfo("Pixel count"                                ,1,1,   "shape"),
"Global<Maximum >"                                           : ObjectFeatureInfo("Maximal intensity (search entire image)"    ,1,1,   "global"),
"Global<Minimum >"                                           : ObjectFeatureInfo("Minimal intensity (search entire image)"    ,1,1,   "global"),
"Histogram"                                                  : ObjectFeatureInfo("Intensity Histogram"                        ,64,64, "intensity"),
"Kurtosis"                                                   : ObjectFeatureInfo("Kurtosis (4th moment) of intensities"       ,1,1,   "intensity"),
"Maximum"                                                    : ObjectFeatureInfo("Maximal intensity"                          ,1,1,   "intensity"),
"Minimum"                                                    : ObjectFeatureInfo("Minimal intensity"                          ,1,1,   "intensity"),
"Mean"                                                       : ObjectFeatureInfo("Mean intensity"                             ,1,1,   "intensity"),
"Quantiles"                                                  : ObjectFeatureInfo("Quantiles (0%, 10%, 25%, 50%, 75%, 90%, 100%) of intensities", 7,7, "intensity"),
"RegionAxes"                                                 : ObjectFeatureInfo("Eigenvectors from PCA (each pixel has unit mass)", 4, 9, "shape",),
"RegionCenter"                                               : ObjectFeatureInfo("Center of mass (each pixel has unit mass)", 2,3, "coordinates"),
"RegionRadii"                                                : ObjectFeatureInfo("Eigenvalues from PCA (each pixel has unit mass)", 2,3, "shape"),
"Skewness"                                                   : ObjectFeatureInfo("Skewness (3rd moment) of intensities", 1,1, "intensity"),
"Sum"                                                        : ObjectFeatureInfo("Sum of pixel intensities", 1,1, "intensity"),
"Variance"                                                   : ObjectFeatureInfo("Variance (2nd moment) of intensities", 1,1, "intensity"),
"Weighted<RegionAxes>"                                       : ObjectFeatureInfo("Eigenvectors from PCA (each pixel has mass according to intensity)", 4,9, "shape"),
"Weighted<RegionCenter>"                                     : ObjectFeatureInfo("Center of mass (each pixel has mass according to its intensity)", 2,3, "shape"),
"Weighted<RegionRadii>"                                      : ObjectFeatureInfo("Eigenvalues from PCA (each pixel has mass according to intensity)", 2,3, "shape"),
"Central<PowerSum<2> >"                                      : ObjectFeatureInfo("",0,0, "unused"),
"Central<PowerSum<3> >"                                      : ObjectFeatureInfo("",0,0, "unused"),
"Central<PowerSum<4> >"                                      : ObjectFeatureInfo("",0,0, "unused"),
"Coord<DivideByCount<Principal<PowerSum<2> > > >"            : ObjectFeatureInfo("",0,0, "unused"),
"Coord<PowerSum<1> >"                                        : ObjectFeatureInfo("",0,0, "unused"),
"Coord<Principal<Kurtosis > >"                               : ObjectFeatureInfo("",0,0, "unused"),
"Coord<Principal<PowerSum<2> > >"                            : ObjectFeatureInfo("",0,0, "unused"),
"Coord<Principal<PowerSum<3> > >"                            : ObjectFeatureInfo("",0,0, "unused"),
"Coord<Principal<PowerSum<4> > >"                            : ObjectFeatureInfo("",0,0, "unused"),
"Coord<Principal<Skewness > >"                               : ObjectFeatureInfo("",0,0, "unused"),
"Weighted<Coord<DivideByCount<Principal<PowerSum<2> > > > >" : ObjectFeatureInfo("",0,0, "unused"),
"Weighted<Coord<PowerSum<1> > >"                             : ObjectFeatureInfo("",0,0, "unused"),
"Weighted<Coord<Principal<Kurtosis > > >"                    : ObjectFeatureInfo("",0,0, "unused"),
"Weighted<Coord<Principal<PowerSum<2> > > >"                 : ObjectFeatureInfo("",0,0, "unused"),
"Weighted<Coord<Principal<PowerSum<3> > > >"                 : ObjectFeatureInfo("",0,0, "unused"),
"Weighted<Coord<Principal<PowerSum<4> > > >"                 : ObjectFeatureInfo("",0,0, "unused"),
"Weighted<Coord<Principal<Skewness > > >"                    : ObjectFeatureInfo("",0,0, "unused"),
"Weighted<PowerSum<0> >"                                     : ObjectFeatureInfo("",0,0, "unused"),
}

import vigra, numpy

shapes = [
    (30,40,50),
    (30,40),
]

for shape in shapes:
    data = numpy.random.random(shape).astype(numpy.float32)
    seg  = numpy.zeros(shape, dtype=numpy.uint32)
    seg.flat = numpy.arange(1,numpy.prod(seg.shape)+1)
    
    features = vigra.analysis.extractRegionFeatures(data, seg, features="all")
    #import IPython; IPython.embed()
    
    for k in features.keys():
        print k
        assert k in r, k
        info = r[k]
        feat = features[k]
        if info.humanName == "":
            continue
        
        realSize = numpy.prod(feat.shape[1:]) if isinstance(feat, numpy.ndarray) and len(feat.shape) > 1 else 1
        if len(shape) == 2:
            assert info.size2D == realSize, "%s has real size %d, but needs %d" % (k, realSize, info.size2D)
        elif len(shape) == 3:
            assert info.size3D == realSize, "%s has real size %d, but needs %d" % (k, realSize, info.size3D)
            
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
    
    def __init__(self, parent=None):
        super(ObjectFeatureSelectionWidget, self).__init__(parent)
        
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
        if not len(sel):
            return
        
        sel = sel[0]
        info = r[self.item2id[sel]]
        self.help.setText("<h2>%s</h2><p>vigra function: <tt>%s</tt></p><p>#channels: %d</p>" \
            % (info.humanName, self.item2id[sel], info.size2D))
        
        

    def handleChecked(self, checked, item, column):
        print self.item2id[item], checked
        
        vigraName = self.item2id[item]
      
        nCh = 0
        nFeat = 0
        for item, vigraName in self.item2id.iteritems():
            if not item.checkState(0) == Qt.Checked:
                continue
            nCh += r[vigraName].size2D
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
           
t = ObjectFeatureSelectionWidget()
t.show()
app.exec_()
