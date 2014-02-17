"""
Give the histogram of labels in a project file.
"""
import sys
import os
import h5py
import numpy

if len(sys.argv) != 2 or not sys.argv[1].endswith(".ilp"):
    sys.stderr.write("Usage: {} <my_project.ilp>\n".format( sys.argv[0] ))
    sys.exit(1)

project_path = sys.argv[1]
if not os.path.exists(project_path):
    sys.stderr.write("Couldn't locate project file: {}\n".format( project_path ))
    sys.exit(2)
else:
    print "Counting labels in project: {}\n".format( project_path )

def print_bincounts(label_names, bins_list, image_name):
    # Sum up the bincounts we got from each label block
    sum_bins = numpy.array( [0]*( len(label_names)+1 ), dtype=numpy.uint32)
    for bins in bins_list:
        zero_pad_bins = numpy.append( bins, [0]*(num_bins-len(bins)) )
        sum_bins += zero_pad_bins
    
    print "Counted a total of {} label points for {}.".format( sum_bins.sum(), image_name )
    max_name_len = max( map(len, label_names ) )
    for name, count in zip( label_names, sum_bins[1:] ):
        print ("{:" + str(max_name_len) + "} : {}").format( name, count )
    print ""

if __name__ == "__main__":
    all_bins = []
    num_bins = 0
    with h5py.File(project_path, 'r') as f:
        try:
            label_names = f['PixelClassification/LabelNames'].value
        except KeyError:
            label_names = map( lambda n: "Label {}".format(n), range(num_bins) )[1:]
        
        # For each image
        for image_index, group in enumerate(f['PixelClassification/LabelSets'].values()):
            # For each label block
            this_img_bins = []
            for block in group.values():
                data = block[:]
                nonzero_coords = numpy.nonzero(data)
                bins = numpy.bincount(data[nonzero_coords].flat)
                this_img_bins.append( bins )
                num_bins = max(num_bins, len(bins))
            all_bins += this_img_bins
            print_bincounts( label_names, this_img_bins, "Image #{}".format( image_index+1 ) )
        
        print_bincounts( label_names, all_bins, "ALL IMAGES")
