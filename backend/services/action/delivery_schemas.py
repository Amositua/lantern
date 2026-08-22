from typing import Literal

from pydantic import BaseModel, ConfigDict


class DeliveryStatusEvent(BaseModel):
    # stands in for a courier's own status webhook -- simulate_delivery.py
    # calls this directly in the demo, the same way a real courier
    # integration would call it from outside
    model_config = ConfigDict(extra="forbid")

    user_id: str
    case_id: str
    order_id: str
    status: Literal["preparing", "out_for_delivery", "delivered"]


class DeliveryStatusResult(BaseModel):
    status: str
    message: str
