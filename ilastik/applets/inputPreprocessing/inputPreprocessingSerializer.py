from ilastik.applets.base.appletSerializer import AppletSerializer, SerialSlot

class InputPreprocessingSerializer(AppletSerializer):
    """
    Serializes the user's data export settings to the project file.
    """
    def __init__(self, operator, projectFileGroupName):
        self.topLevelOperator = operator
        super(InputPreprocessingSerializer, self).__init__(projectFileGroupName,
                                                   slots=[ SerialSlot(operator.CropRoi) ])
