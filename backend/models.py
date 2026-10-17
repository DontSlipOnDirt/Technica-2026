# models.py
# Shared data shapes for the whole team.
# Everyone imports from here. Don't rename fields without telling the team.

from dataclasses import dataclass, field
from typing import List, Literal, Optional

# The only three decisions allowed, spelled exactly like this.
Decision = Literal["allow", "confirm", "hold"]


@dataclass
class TransferRequest:
    """What the voice agent asks for when the user wants to move money."""
    from_account_id: str          # Nessie account ID sending the money
    to_account_id: str            # Nessie account ID receiving the money
    amount: float                 # Always dollars, e.g. 2000.00
    user_said: str = ""           # What the user said out loud
    description: str = ""         # Optional note
    requested_at: str = ""        # Format: "2026-10-17T14:32:00"


@dataclass
class PastTransfer:
    """One transfer from the user's history."""
    to_account_id: str
    amount: float
    made_at: str                  # Format: "2026-10-17T14:32:00"


@dataclass
class TrustedContact:
    """The family member who gets alerted when a transfer is held."""
    name: str
    phone: str


@dataclass
class UserHistory:
    """What the data person provides from Nessie."""
    known_payees: List[str]                   # Account IDs they've sent to before
    average_transfer: float                   # Their usual transfer amount
    current_balance: float                    # Money in the sending account now
    recent_transfers: List[PastTransfer] = field(default_factory=list)
    trusted_contact: Optional[TrustedContact] = None


@dataclass
class FraudDecision:
    """What the fraud check sends back."""
    decision: Decision            # "allow", "confirm", or "hold"
    risk_score: int               # 0 to 100
    reasons: List[str]            # Plain-English reasons, e.g. ["New payee"]
    spoken_message: str           # What the voice agent reads out loud
    transfer_id: str              # So a held transfer can be found later


@dataclass
class FamilyAlert:
    """Sent to the trusted contact when a transfer is held. The app shows these."""
    transfer_id: str
    contact_name: str
    contact_phone: str
    message: str                  # Plain-English alert text
    created_at: str               # Format: "2026-10-17T14:32:00"