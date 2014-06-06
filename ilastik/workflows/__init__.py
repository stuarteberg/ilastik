###############################################################################
#   ilastik: interactive learning and segmentation toolkit
#
#       Copyright (C) 2011-2014, the ilastik developers
#                                <team@ilastik.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# In addition, as a special exception, the copyright holders of
# ilastik give you permission to combine ilastik with applets,
# workflows and plugins which are not covered under the GNU
# General Public License.
#
# See the LICENSE file for details. License information is also available
# on the ilastik web site at:
#		   http://ilastik.org/license.html
###############################################################################
import logging
logger = logging.getLogger(__name__)

import pixelClassification

try:
    import objectClassification
except ImportError as e:
    logger.warn("Failed to import object workflow; check dependencies: " + str(e))

try:
    import carving 
except ImportError as e:
    logger.warn( "Failed to import carving workflow; check cylemon dependency: " + str(e) )

try:
    import tracking
except ImportError as e:
    logger.warn( "Failed to import tracking workflow; check pgmlink dependency: " + str(e) )
    
try:
    import counting
except ImportError as e:
    logger.warn("Failed to import counting workflow; check dependencies: " + str(e))


import seededWatershed

# Examples
import ilastik.config

if ilastik.config.cfg.getboolean('ilastik', 'debug'):
    import vigraWatershed
    import examples.layerViewer
    import examples.thresholdMasking
    import examples.deviationFromMean
    import examples.labeling
    import examples.dataConversion
