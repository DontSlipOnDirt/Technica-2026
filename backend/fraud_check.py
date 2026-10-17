# fraud_check.py
# Checks every transfer before money moves.
# Adds up points for warning signs, then decides: allow, confirm, or hold.
# Held transfers alert the trusted contact and need a PIN to release.

import os
import re
import uuid
from datetime import datetime, timedelta

from models import TransferRequest, UserHistory, FraudDecision, PastTransfer, TrustedContact, FamilyAlert
from gemini_signals import scam_signals

# PIN that releases a held transfer. Set RELEASE_PIN in .env; "1234" is the demo default.
RELEASE_PIN = os.environ.get("RELEASE_PIN", "1234")

# Kept in memory for the hackathon. Resets when the server restarts.
# transfer_id -> "allow", "confirm", "hold", or "released"
TRANSFER_STATUS = {}
# transfer_id -> the original TransferRequest, for held transfers
HELD_TRANSFERS = {}
# Every family alert sent, newest last
ALERTS = []

# Words and phrases to watch for in what the user said.
SCAM_PHRASES = [
    "safe account",
    "fraud department",
    "bail",
    "gift card",
    "don't tell",
    "irs",
    "warrant",
    "arrest",
]

URGENCY_PHRASES = [
    "right now",
    "immediately",
    "hurry",
    "before it's too late",
]

# Points for each warning sign. Tune these while testing.
POINTS_NEW_PAYEE = 25
POINTS_LARGE_AMOUNT = 25
POINTS_MOST_OF_BALANCE = 20
POINTS_SCAM_PHRASE = 30
POINTS_URGENCY = 15
POINTS_RAPID_TRANSFERS = 30
POINTS_GEMINI_SCAM_STORY = 30

# Score cutoffs for each decision.
CONFIRM_AT = 30
HOLD_AT = 60


def _find_phrase(text: str, phrases: list) -> str:
    """Return the first phrase found as whole words in text, or "" if none.
    Whole words only, so "irs" doesn't match "first"."""
    for phrase in phrases:
        if re.search(r"\b" + re.escape(phrase) + r"\b", text):
            return phrase
    return ""


def _count_recent_transfers(request: TransferRequest, history: UserHistory, minutes: int = 10) -> int:
    """How many transfers the user made in the last few minutes before this request."""
    if not request.requested_at:
        return 0
    now = datetime.fromisoformat(request.requested_at)
    window_start = now - timedelta(minutes=minutes)
    count = 0
    for past in history.recent_transfers:
        made_at = datetime.fromisoformat(past.made_at)
        if window_start <= made_at <= now:
            count += 1
    return count


def check_transfer(request: TransferRequest, history: UserHistory) -> FraudDecision:
    """
    Look at a transfer request and decide: allow, confirm, or hold.

    Other people's code calls this before ANY money moves.
    """
    transfer_id = "t_" + uuid.uuid4().hex[:8]

    risk_score = 0
    reasons = []
    said = request.user_said.lower()

    # Rule 1: sending to someone they've never paid before.
    if request.to_account_id not in history.known_payees:
        risk_score += POINTS_NEW_PAYEE
        reasons.append("This is someone you haven't sent money to before")

    # Rule 2: much bigger than their usual transfer.
    if history.average_transfer > 0 and request.amount > 3 * history.average_transfer:
        risk_score += POINTS_LARGE_AMOUNT
        reasons.append("This is much larger than your usual transfer")

    # Rule 3: more than half of everything in the account.
    if history.current_balance > 0 and request.amount > 0.5 * history.current_balance:
        risk_score += POINTS_MOST_OF_BALANCE
        reasons.append("This is more than half of your balance")

    # Rule 4: known scam phrases in what they said.
    scam_phrase = _find_phrase(said, SCAM_PHRASES)
    if scam_phrase:
        risk_score += POINTS_SCAM_PHRASE
        reasons.append(f'You mentioned "{scam_phrase}", which is common in scams')

    # Rule 5: pressure to act fast.
    if _find_phrase(said, URGENCY_PHRASES):
        risk_score += POINTS_URGENCY
        reasons.append("Someone may be pressuring you to act fast")

    # Rule 6: several transfers in a short time.
    if _count_recent_transfers(request, history) >= 2:
        risk_score += POINTS_RAPID_TRANSFERS
        reasons.append("You've made several transfers in just a few minutes")

    # Rule 7: Gemini reads what they said for scam stories the word lists miss.
    # Skipped if Rule 4 already caught a scam phrase, so the same thing isn't counted twice.
    # Gemini only adds points. If it's unavailable, the rules above still decide.
    if not scam_phrase:
        signals = scam_signals(request.user_said)
        if signals and (signals.impersonation or signals.unusual_payment):
            risk_score += POINTS_GEMINI_SCAM_STORY
            reasons.append("What you described sounds like a common scam")

    risk_score = min(risk_score, 100)

    # Turn the score into a decision and a message for the voice agent.
    if risk_score >= HOLD_AT:
        decision = "hold"
        HELD_TRANSFERS[transfer_id] = request
        alert_line = ""
        if history.trusted_contact:
            send_family_alert(history.trusted_contact, request, reasons, transfer_id)
            alert_line = f"I've also let {history.trusted_contact.name} know. "
        spoken_message = (
            "I've paused this transfer to keep your money safe. "
            + ". ".join(reasons)
            + ". Your bank will never ask you to move money to keep it safe. "
            + alert_line
            + "If this is a mistake, you can release it with your PIN."
        )
    elif risk_score >= CONFIRM_AT:
        decision = "confirm"
        spoken_message = (
            "Before you send this, please double-check. "
            + ". ".join(reasons)
            + ". If you're sure, tap Confirm."
        )
    else:
        decision = "allow"
        spoken_message = "Okay. Please tap Confirm to send this transfer."

    TRANSFER_STATUS[transfer_id] = decision

    return FraudDecision(
        decision=decision,
        risk_score=risk_score,
        reasons=reasons,
        spoken_message=spoken_message,
        transfer_id=transfer_id,
    )


def send_family_alert(contact: TrustedContact, request: TransferRequest, reasons: list, transfer_id: str) -> FamilyAlert:
    """Create an alert for the trusted contact. The app shows it on their screen."""
    alert = FamilyAlert(
        transfer_id=transfer_id,
        contact_name=contact.name,
        contact_phone=contact.phone,
        message=(
            f"Hi {contact.name}, we paused a ${request.amount:,.2f} transfer from your "
            f"family member's account because it looked like a scam: "
            + "; ".join(reason.lower() for reason in reasons)
            + ". Please give them a call."
        ),
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    ALERTS.append(alert)
    return alert


def get_alerts() -> list:
    """All family alerts so far, newest last. The app calls this to show them."""
    return list(ALERTS)


def release_hold(transfer_id: str, pin: str) -> bool:
    """Release a held transfer if the PIN is right. Returns True if released."""
    if TRANSFER_STATUS.get(transfer_id) != "hold":
        return False
    if pin != RELEASE_PIN:
        return False
    TRANSFER_STATUS[transfer_id] = "released"
    return True


def is_cleared_to_send(transfer_id: str) -> bool:
    """
    The money-moving code (execute_transfer) MUST call this first.
    Only transfers this file has checked and approved can be sent.
    """
    return TRANSFER_STATUS.get(transfer_id) in ("allow", "confirm", "released")


# ------------------------------------------------------------------
# Tests: runs only when you run this file directly.
# ------------------------------------------------------------------
if __name__ == "__main__":
    NOW = "2026-10-17T14:35:00"

    # Tests never call the real Gemini. Rule 7 gets a stand-in further down.
    scam_signals = lambda said: None

    def make_history(extra_transfers=None) -> UserHistory:
        """A pretend user: usually sends ~$100, has $3,000, pays her daughter and the electric company."""
        return UserHistory(
            known_payees=["daughter_account", "electric_company"],
            average_transfer=100.00,
            current_balance=3000.00,
            recent_transfers=[
                PastTransfer(to_account_id="daughter_account", amount=50.00, made_at="2026-10-10T12:00:00"),
            ] + (extra_transfers or []),
            trusted_contact=TrustedContact(name="Maria (daughter)", phone="555-0100"),
        )

    # (test name, request, history, expected decision)
    tests = [
        (
            "$85 electric bill",
            TransferRequest("grandma_checking", "electric_company", 85.00,
                            user_said="Pay my electric bill", requested_at=NOW),
            make_history(),
            "allow",
        ),
        (
            "$50 to daughter",
            TransferRequest("grandma_checking", "daughter_account", 50.00,
                            user_said="Send fifty dollars to Maria", requested_at=NOW),
            make_history(),
            "allow",
        ),
        (
            "$400 to someone new",
            TransferRequest("grandma_checking", "friend_account", 400.00,
                            user_said="Send four hundred dollars to my friend Joe", requested_at=NOW),
            make_history(),
            "confirm",
        ),
        (
            "Fake fraud department, safe account",
            TransferRequest("grandma_checking", "scammer_account", 2000.00,
                            user_said="The fraud department told me to move my money to a safe account right now",
                            requested_at=NOW),
            make_history(),
            "hold",
        ),
        (
            "Grandson in jail, needs bail",
            TransferRequest("grandma_checking", "scammer_account", 1800.00,
                            user_said="My grandson is in jail and needs bail money right now",
                            requested_at=NOW),
            make_history(),
            "hold",
        ),
        (
            "Three $500 transfers in 5 minutes",
            TransferRequest("grandma_checking", "scammer_account", 500.00,
                            user_said="Send another five hundred dollars", requested_at=NOW),
            make_history(extra_transfers=[
                PastTransfer(to_account_id="scammer_account", amount=500.00, made_at="2026-10-17T14:30:00"),
                PastTransfer(to_account_id="scammer_account", amount=500.00, made_at="2026-10-17T14:33:00"),
            ]),
            "hold",
        ),
    ]

    passed = 0
    for name, request, history, expected in tests:
        result = check_transfer(request, history)
        ok = result.decision == expected
        passed += ok
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {name}: got {result.decision} (score {result.risk_score}), expected {expected}")
        for reason in result.reasons:
            print(f"        - {reason}")

    # Step 7 tests: holds, family alerts, and PIN release.
    print("\nHold and alert tests:")
    hold_checks = []

    scam = check_transfer(
        TransferRequest("grandma_checking", "scammer_account", 2000.00,
                        user_said="Move it to a safe account right now", requested_at=NOW),
        make_history(),
    )
    alerts = get_alerts()
    hold_checks.append(("Held transfer creates a family alert",
                        any(a.transfer_id == scam.transfer_id for a in alerts)))
    hold_checks.append(("Alert is addressed to the daughter",
                        alerts[-1].contact_name == "Maria (daughter)"))
    hold_checks.append(("Spoken message says the contact was told",
                        "Maria (daughter)" in scam.spoken_message))
    hold_checks.append(("Held transfer is NOT cleared to send",
                        not is_cleared_to_send(scam.transfer_id)))
    hold_checks.append(("Wrong PIN does not release it",
                        not release_hold(scam.transfer_id, "0000") and not is_cleared_to_send(scam.transfer_id)))
    hold_checks.append(("Right PIN releases it",
                        release_hold(scam.transfer_id, RELEASE_PIN) and is_cleared_to_send(scam.transfer_id)))

    normal = check_transfer(
        TransferRequest("grandma_checking", "electric_company", 85.00,
                        user_said="Pay my electric bill", requested_at=NOW),
        make_history(),
    )
    hold_checks.append(("Normal transfer is cleared to send", is_cleared_to_send(normal.transfer_id)))
    hold_checks.append(("Normal transfer can't be 'released'", not release_hold(normal.transfer_id, RELEASE_PIN)))
    hold_checks.append(("Unknown transfer is NOT cleared", not is_cleared_to_send("t_made_up")))

    for name, ok in hold_checks:
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n  Example alert: {alerts[-1].message}")
    print(f"  Example spoken message: {scam.spoken_message}")

    # Rule 7 tests: a bank-impersonation story with none of the listed scam words.
    print("\nGemini tests:")
    gemini_checks = []
    from gemini_signals import ScamSignals

    story = TransferRequest("grandma_checking", "new_account", 400.00,
                            user_said="A man from my bank says my account was hacked and I need to move it to a new one",
                            requested_at=NOW)

    scam_signals = lambda said: None
    without = check_transfer(story, make_history())
    gemini_checks.append(("Without Gemini, the story only gets a confirm", without.decision == "confirm"))

    scam_signals = lambda said: ScamSignals(impersonation=True, pressure=False, unusual_payment=True,
                                            evidence=["A man from my bank says"])
    with_gemini = check_transfer(story, make_history())
    gemini_checks.append(("With Gemini, the same story is held", with_gemini.decision == "hold"))
    gemini_checks.append(("The reason mentions a scam",
                          "What you described sounds like a common scam" in with_gemini.reasons))

    phrase_case = check_transfer(
        TransferRequest("grandma_checking", "new_account", 400.00,
                        user_said="Move it to a safe account", requested_at=NOW),
        make_history(),
    )
    gemini_checks.append(("A listed scam phrase isn't counted twice",
                          phrase_case.reasons.count("What you described sounds like a common scam") == 0))

    for name, ok in gemini_checks:
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if name.startswith("With Gemini"):
            print(f"        score {without.risk_score} -> {with_gemini.risk_score}")

    print(f"\n{passed}/{len(tests) + len(hold_checks) + len(gemini_checks)} tests passed")
