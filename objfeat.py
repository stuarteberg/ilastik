from collections import defaultdict
import cgi
from PyQt4.QtGui import *
from PyQt4.QtCore import *

class ObjectFeatureInfo(object):
    def __init__(self, humanName, size, group):
        self.humanName = humanName
        self.group  = group
        self._size = size
        self.meaning = None
        
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
        else:
            raise RuntimeError("not implemented")

# Build object feature info dictionary        

def getVigraObjectFeatureInfos():
    r = {}

    o = ObjectFeatureInfo("Coordinate of pixel with maximal intensity" ,"coor",   "coordinates")
    o.meaning = "position of the point with maximum intensity"
    r["Coord<ArgMaxWeight >"] = o

    o = ObjectFeatureInfo("Coordinate of pixel with minimal intensity" ,"coor",   "coordinates")
    o.meaning = "position of the point with minimum intensity"
    r["Coord<ArgMinWeight >"] = o

    o = ObjectFeatureInfo("Lower right coordinate of bounding box"     ,"coor",   "coordinates")
    o.meaning = "upper bound of the regions bounding box"
    r["Coord<Maximum >"] = o

    o = ObjectFeatureInfo("Upper left coordinate of bounding box"      ,"coor",   "coordinates")  
    o.meaning = "lower bound of the regions bounding box"
    r["Coord<Minimum >"] = o
    
    o = ObjectFeatureInfo("Pixel count" ,1,   "shape")
    o.meaning = "size of the region (number of pixels)"
    r["Count"] = o
    
    o= ObjectFeatureInfo("Maximal intensity (search entire image)",1,   "global")
    o.meaning = "TODO"
    r["Global<Maximum >"] = o
    
    o= ObjectFeatureInfo("Minimal intensity (search entire image)",1,   "global")
    o.meaning = "TODO"
    r["Global<Minimum >"] = o 
    
    o= ObjectFeatureInfo("Intensity Histogram",64,   "intensity")
    o.meaning = "TODO"
    r["Histogram"] = o
    
    o= ObjectFeatureInfo("Kurtosis (4th moment) of intensities",1,   "intensity")
    o.meaning = "intensity kurtosis (computed per channel)"
    r["Kurtosis"] = o 
    
    o= ObjectFeatureInfo("Maximal intensity","ch",   "intensity")
    o.meaning = "maximum intensity (computed per channel)"
    r["Maximum"] = o 
    
    o= ObjectFeatureInfo("Minimal intensity" ,"ch",   "intensity")
    o.meaning = "minimum intensity (computed per channel)"
    r["Minimum"] = o 

    o= ObjectFeatureInfo("Mean intensity" ,"ch",   "intensity")  
    o.meaning = "mean intensity (computed per channel)"
    r["Mean"] = o
        
    o= ObjectFeatureInfo("Quantiles (0%, 10%, 25%, 50%, 75%, 90%, 100%) of intensities", 7, "intensity")
    o.meaning = "quantiles of the intensity"
    r["Quantiles"] = o                                                  
        
    o=  ObjectFeatureInfo("Eigenvectors from PCA (each pixel has unit mass)", "coor2", "shape",)
    o.meaning = "axes of a local coordinate system aligned to the region"
    r["RegionAxes"] = o
        
    o= ObjectFeatureInfo("Center of mass (each pixel has unit mass)", "coor", "coordinates")
    o.meaning = "geometric center of the region"
    r["RegionCenter"] = o 

    o= ObjectFeatureInfo("Eigenvalues from PCA (each pixel has unit mass)", "coor", "shape")
    o.meaning = "radii of the major and minor region axes"
    r["RegionRadii"] = o 

    o= ObjectFeatureInfo("Skewness (3rd moment) of intensities", "ch", "intensity")
    o.meaning = "intensity skewness (computed per channel)"
    r["Skewness"] = o 

    o= ObjectFeatureInfo("Sum of pixel intensities", "ch", "intensity")
    o.meaning = "sum of the intensities (computed per channel)"
    r["Sum"] = o

    o= ObjectFeatureInfo("Variance (2nd moment) of intensities", "ch", "intensity")
    o.meaning = "intensity variance (computed per channel)"
    r["Variance"] = o                                                   

    o= ObjectFeatureInfo("Covariance", "ch2", "intensity")
    o.meaning = "covariance matrix for multi-channel data"
    r["Covariance"] = o                                                

    o= ObjectFeatureInfo("Eigenvectors from PCA (each pixel has mass according to intensity)", "coor2", "shape")
    o.meaning = "axes of inertia, when intensities are interpreted as mass"
    r["Weighted<RegionAxes>"] = o                                      

    o= ObjectFeatureInfo("Center of mass (each pixel has mass according to its intensity)", "coor", "shape")
    o.meaning = "center of mass"
    r["Weighted<RegionCenter>"] = o                                     

    o= ObjectFeatureInfo("Eigenvalues from PCA (each pixel has mass according to intensity)", "coor", "shape")
    o.meaning = "square-root of the moments of inertia"
    r["Weighted<RegionRadii>"] = o                                      

    o= ObjectFeatureInfo("","ch", "unused")
    o.meaning = "second central moment of the intensities"
    r["Central<PowerSum<2> >"] = o                                      

    o= ObjectFeatureInfo("","ch", "unused")
    o.meaning = "third central moment"
    r["Central<PowerSum<3> >"] = o                                      

    o= ObjectFeatureInfo("","ch", "unused")
    o.meaning = "fourth central moment"
    r["Central<PowerSum<4> >"] = o                           

    o= ObjectFeatureInfo("","coor", "unused")
    r["Coord<DivideByCount<Principal<PowerSum<2> > > >"] = o 

    o= ObjectFeatureInfo("","coor", "unused")
    r["Coord<PowerSum<1> >"] = o   

    o= ObjectFeatureInfo("","coor", "unused")
    r["Coord<Principal<Kurtosis > >"] = o

    o=  ObjectFeatureInfo("","coor", "unused")
    r["Coord<Principal<PowerSum<2> > >"] = o                          

    o= ObjectFeatureInfo("","coor", "unused")
    r["Coord<Principal<PowerSum<3> > >"] = o 

    o=  ObjectFeatureInfo("","coor", "unused")
    r["Coord<Principal<PowerSum<4> > >"] = o  

    o=  ObjectFeatureInfo("","coor", "unused")
    r["Coord<Principal<Skewness > >"] = o    

    o=  ObjectFeatureInfo("","coor", "unused")
    r["Weighted<Coord<DivideByCount<Principal<PowerSum<2> > > > >"] = o 

    o=  ObjectFeatureInfo("","coor", "unused")
    r["Weighted<Coord<PowerSum<1> > >"] = o                            

    o=  ObjectFeatureInfo("","coor", "unused")
    o.meaning = "kurtosis along axes of inertia"
    r["Weighted<Coord<Principal<Kurtosis > > >"] = o

    o=  ObjectFeatureInfo("","coor", "unused")
    r["Weighted<Coord<Principal<PowerSum<2> > > >"] = o  

    o=  ObjectFeatureInfo("","coor", "unused")
    r["Weighted<Coord<Principal<PowerSum<3> > > >"] = o 

    o=  ObjectFeatureInfo("","coor", "unused")
    r["Weighted<Coord<Principal<PowerSum<4> > > >"] = o 

    o=  ObjectFeatureInfo("","coor", "unused")
    o.meaning = "skewness along axes of inertia"
    r["Weighted<Coord<Principal<Skewness > > >"] = o

    o=  ObjectFeatureInfo("","ch", "unused")
    r["Weighted<PowerSum<0> >"] = o            

    o=   ObjectFeatureInfo("","ch", "unused")
    r["Principal<Maximum >"] = o            

    o=  ObjectFeatureInfo("kurtosis of intensities after principal component projection","ch", "intensity")
    o.meaning = "kurtosis of intensities after principal component projection"
    r["Principal<Kurtosis >"] = o      

    o=  ObjectFeatureInfo("","ch", "unused")
    r["Principal<Minimum >"] = o    

    o=  ObjectFeatureInfo("","ch", "unused")
    r["Principal<PowerSum<2> >"] = o       

    o=  ObjectFeatureInfo("","ch", "unused")
    r["Principal<PowerSum<3> >"] = o  

    o=  ObjectFeatureInfo("","ch", "unused")
    r["Principal<PowerSum<4> >"] = o  

    o=  ObjectFeatureInfo("skewness of intensities after principal component projection","ch", "intensity")
    o.meaning = "skewness of intensities after principal component projection"
    r["Principal<Skewness >"] = o   

    o=  ObjectFeatureInfo("variance of intensities after principal component projection","ch", "intensity")
    o.meaning = "variance of intensities after principal component projection"
    r["Principal<Variance>"] = o  

    o=  ObjectFeatureInfo("eigenvectors of the PCA of the intensities","ch2", "intensity")
    o.meaning = "eigenvectors of the PCA of the intensities"
    r["PrincipalAxes"] = o                                           
    
    return r

#-----------------------------------------------------------------------------

import vigra, numpy

def testObjectFeatureDefinitions(r):
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
                #assert info.meaning is not None
                
                print "%%%%",k
                feat = features[k]
                #if info.humanName == "":
                #    continue
                
                realSize = numpy.prod(feat.shape[1:]) if isinstance(feat, numpy.ndarray) and len(feat.shape) > 1 else 1
                print k
                print realSize
                print info.size(len(shape), channel)
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
   
   
#-----------------------------------------------------------------------------
   
class ObjectFeatureSelectionWidget(QWidget):
    
    msg_NoFeatureSelected = "No feature selected"
    msg_FeaturesSelected  = "%d features selected, %d channels in total"
    
    def __init__(self, dim, channels, infos, parent=None):
        super(ObjectFeatureSelectionWidget, self).__init__(parent)
        
        self.dim        = dim
        self.channels   = channels
        self.treeWidget = None
        self.label      = None
        self.item2id    = {}
        self.help       = QTextBrowser(self)
        self.infos      = infos

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
        for key, group in groupby(self.infos, lambda x: self.infos[x].group):
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
                child.setText(0, self.infos[v].humanName)
                self.item2id[child] = v
                groupRoot.addChild(child)
                child.setCheckState(0, Qt.Unchecked)
        
        pluginRoot.setExpanded(True)
        self.treeWidget.itemChanged.connect(self._handleItemChanged)
        self.treeWidget.itemSelectionChanged.connect(self._handleSelectionChanged)
        
    def selectedFeatures(self):
        sel = []
        for item, vigraName in self.item2id.iteritems():
            if not item.checkState(0) == Qt.Checked:
                continue
            sel.append(vigraName)
        return sorted(sel)


    #private:

    def _handleSelectionChanged(self):
        sel = self.treeWidget.selectedItems()
        assert len(sel) <= 1
        if not len(sel) or sel[0] not in self.item2id:
            self.help.setText("")
            return
        
        sel = sel[0]
        info = self.infos[self.item2id[sel]]
        self.help.setText("<h2>%s</h2><p>vigra function: <tt>%s</tt></p><p>#channels: %d</p><p><i>Meaning:</i><br />%s</p>" \
            % (info.humanName, cgi.escape(self.item2id[sel]), info.size(self.dim, self.channels), "n/a" if info.meaning is None else info.meaning))

    def _handleChecked(self, checked, item, column):
        print self.item2id[item], checked
        
        vigraName = self.item2id[item]
      
        nCh = 0
        nFeat = 0
        for item, vigraName in self.item2id.iteritems():
            if not item.checkState(0) == Qt.Checked:
                continue
            nCh += self.infos[vigraName].size(self.dim, self.channels)
            nFeat += 1
            
        if nFeat == 0:
            self.label.setText(self.msg_NoFeatureSelected)
        else:
            self.label.setText(self.msg_FeaturesSelected % (nFeat, nCh))
    
    def _handleItemChanged(self, item, column):
        self.treeWidget.blockSignals(True)
        if item.checkState(column) == Qt.Checked:
            self._handleChecked(True, item, column)
        elif item.checkState(column) == Qt.Unchecked:
            self._handleChecked(False, item, column)
        self.treeWidget.blockSignals(False)
        
if __name__ == "__main__":
    infos = getVigraObjectFeatureInfos()
    testObjectFeatureDefinitions(infos)

    app = QApplication([])
    
    t = ObjectFeatureSelectionWidget(2, 0, infos)
    t.show()
    app.exec_()
