"""Private fixture TF buffer with independently controllable map-edge delivery."""
from tf2_ros import Buffer
from tf_fault_probe import TfDeliveryFilter


class ProbeTfBuffer(Buffer):
    def __init__(self):
        self.delivery=TfDeliveryFilter()
        super().__init__()

    def set_transform(self, transform, authority):
        if self.delivery.admit(transform):
            return super().set_transform(transform,authority)
