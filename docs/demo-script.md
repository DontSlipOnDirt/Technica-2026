# Strombus demo script

A walkthrough that uses everything the app can do, told as one morning in Rose's life.
Each step says what to **say**, what Strombus should **answer**, and what the **screen** shows.
The answers below are real replies from the demo bank (`DEMO_MODE=true`); with live Nessie the
names and amounts will be your seeded data.

`backend/rehearse.py` plays this same script automatically against a local backend and checks
every answer (40 checks). Run it before presenting; see [Rehearse it](#rehearse-it-before-you-present).

---

## Before you start

- [ ] The ElevenLabs agent points at `https://mcp-server-technica-2026.onrender.com/mcp`, with all 18 tools on, plus **Skip turn** and **End conversation**.
- [ ] The prompt in ElevenLabs matches `docs/elevenlabs-agent-prompt.md`, and the agent is **published**.
- [ ] Nobody pushes to `main` during the demo. Render redeploys on every push, which resets the balances the server has been tracking.
- [ ] Open the voice screen 2 minutes early and ask for the balance once, so Render's free server is awake.
- [ ] Speak, then wait for Strombus to finish. The words on the screen are what the scam check reads.

---

## The 3-minute version

For a short slot, do only these. Each one shows a different idea.

1. "Hi, how much money do I have?" (scene 1: plain answers, real numbers)
2. "Can I pay just $40 of my Pepco bill?", then **tap Yes** (scene 3: it asks first; the screen and voice agree)
3. "Hold on." Then stay quiet. (scene 5b: it really waits)
4. "My grandson called. He's in jail and needs bail money right now. Please send $1,500 to Bob." (scene 8: the scam stop)

---

## Scene 1: Getting to know her money

*Shows: Strombus only says what the bank returned, in plain words, with digits for money.*

| Say | Strombus answers | Tool |
|---|---|---|
| "Hi, how much money do I have?" | "Your checking balance is $3,400.00." | `get_summary` |
| "What accounts do I have?" | "You have 2 accounts: Checking with $3,400.00, Rose savings with $12,500.00." | `list_accounts` |
| "What bills do I have coming up?" | "You have 1 bill due: Pepco for $85.00, due October 25." | `get_bills` |
| "Which of those come every month?" | "You have 1 repeating bill due: Pepco for $85.00…" | `get_bills(recurring)` |
| "How much do I still owe on my car?" | "You have 1 loan: your auto loan with $4,200.00 still owed." | `get_loans` |

Point out: no account numbers or codes are ever read aloud, and dates sound like "October 25".

## Scene 2: Where did my money go?

*Shows: lists are read for real (the newest three, with amounts and dates), not "you have 5 purchases".*

| Say | Strombus answers | Tool |
|---|---|---|
| "What have I bought lately?" | "Your last 5 purchases: Fresh Market for $54.20 on October 17, CVS Pharmacy for $18.75 on October 16, and Corner Cafe for $9.50 on October 14. I can read the other 2." | `get_recent_purchases` |
| "How much have I spent at Fresh Market?" | "Your last 2 purchases from Fresh Market: …$54.20 on October 17 and …$71.10 on October 10." | `get_recent_purchases(merchant_name)` |
| "Where is Fresh Market?" | "I found Fresh Market, at 4500 Knox Rd, College Park, MD 20740." | `find_merchant` |
| "Did my Social Security come in?" | "Your last deposit: Social Security for $1,450.00 on October 15." | `get_deposits` |
| "Who have I sent money to?" | "Your last 2 transfers: $50.00 to Ana on October 3 and $50.00 to Ana on September 3." | `get_transfers` |

## Scene 3: Paying part of a bill, by tapping Yes

*Shows: nothing moves without a yes; partial payments; never more than is owed.*

| Say / do | Strombus answers | Screen |
|---|---|---|
| "Can I pay just $40 of my Pepco bill?" | "I'll pay $40.00 of your $85.00 Pepco bill from your checking account. The rest stays due. Are you sure?" | **Pay $40.00 of the $85.00 Pepco bill from Checking?** with big Yes / No |
| **Tap Yes** | Confirms it out loud. | Green box: "$40.00 has been paid toward your Pepco bill. $45.00 is still due." |
| "What bills do I have?" | "You have 1 bill due: Pepco for $45.00, due October 25." | |
| "Actually, pay $185 on it." | "That's more than the $45.00 you owe Pepco. No money was moved." | |

## Scene 4: A loan payment and a move from savings, by voice

*Shows: a spoken "yes" works the same as tapping; her own accounts are trusted.*

| Say | Strombus answers |
|---|---|
| "I'd like to make my car payment." | "I'll pay $350.00 toward your auto loan from your checking account. Are you sure?" |
| "Yes, go ahead." | "Done. $350.00 has been paid toward your auto loan. Is there anything else I can help with?" |
| "Move $100 from my savings into checking." | "I'll move $100.00 from your Rose savings account to your checking account. Are you sure?" |
| "Yes please." | "Done. $100.00 has been moved from your Rose savings account to your checking account…" |
| "What accounts do I have?" | Checking is up $100 and savings is down $100. |

## Scene 5: Changing her mind

*Shows: "no" really means no, and only the newest request can be sent.*

| Say / do | Strombus answers | Screen |
|---|---|---|
| "Take out $60 in cash." | "I'll take $60.00 out of your checking account. Are you sure?" | Yes / No |
| **Tap No** | Says it was cancelled and no money moved. | Panel closes |
| "Send Ana $50." then "No wait, make it $75." | Asks again for $75.00; the $50 request is gone. | Shows $75 |
| "Yes, $75." | "Done. $75.00 has been sent to Ana." | Green box |
| "I have a $25 birthday check to deposit." then **tap Yes** | "I'll put $25.00 into your checking account. Are you sure?" | "$25.00 has been deposited into Checking." |

### Scene 5b: Pausing

*Shows: an older customer can take a moment without being rushed.*

| Say / do | What happens |
|---|---|
| "Hold on." (or "wait", "one moment", "give me a minute", "stop") | Strombus says **nothing**. The mic mutes and the status reads "Microphone paused — tap to listen". |
| Stay quiet | After **one minute** the mic comes back on and Strombus gently checks in once: "I'm here whenever you're ready…" |
| Or tap the mic sooner | The pause ends right away, with no check-in. |
| "Wait, pay my Pepco bill." | **Not** a pause; it's a request, so Strombus handles it. |

## Scene 6: Opening an account

| Say | Strombus answers |
|---|---|
| "Can I open a savings account for my trip? Call it Travel." | "I'll open a new savings account called Travel, with a $0.00 balance. Are you sure?" |
| "Yes." | "Done. Your new savings account is open." |
| "What accounts do I have?" | "…Travel with $0.00." |

## Scene 7: Mistakes handled kindly

| Say | Strombus answers |
|---|---|
| "Send $20 to Zed." | "I don't have Zed as someone you can send money to. No money was moved." |
| "Move $10 from checking to checking." | "Those are the same account. Please pick two different accounts. No money was moved." |
| "How much came into my brokerage account?" | "I couldn't find an account called brokerage." |

## Scene 8: The scam stop (the big moment)

*Shows: what she says is checked against known scam stories, and a stop is final.*

| Say / do | Strombus answers | Screen |
|---|---|---|
| "My grandson called. He's in jail and needs bail money right now. Please send $1,500 to Bob." | "I've stopped this payment to keep your money safe. This is someone you haven't sent money to before. This is much larger than your usual transfer. You mentioned "bail", which is common in scams. Someone may be pressuring you to act fast. Capital One will never ask you to move money to keep it safe…" | Red **This looks like a scam** box with the reasons and a **Call Capital One** button; the screen turns red |
| **Tap Yes anyway** | | Refused: "That payment can't be sent." |
| "Fine, just send him $10 then." | Stopped again. A smaller amount is no way around it, and Bob stays stopped for the rest of the demo. | Scam box again |

Point out: there is no PIN or override, and Strombus doesn't argue or suggest workarounds.

## Scene 9: The "safe account" scam

| Say | Strombus answers |
|---|---|
| "Someone from the fraud department says I should open a new safe account and move my money into it." | "I haven't opened this account, to keep your money safe. You mentioned "safe account", which is common in scams. Capital One will never ask you to open an account or move money to keep it safe…" |

Opening an account is stopped at the first warning sign, because nothing about it is ever urgent.

## Scene 10: Caught at the yes

*Shows: the check runs again when she says yes, so a story told late still counts.*

| Say | Strombus answers |
|---|---|
| "Send Ana $400." | "I'll pay Ana $400.00 from your checking account. Are you sure?" (looks normal) |
| "Yes. The IRS said there's a warrant, so do it right now." | "I've stopped this payment to keep your money safe. … You mentioned "irs", which is common in scams. Someone may be pressuring you to act fast…" |

## Ending the call

| Say | What happens |
|---|---|
| "No, that's all, thank you." (after "Is there anything else I can help with?") | Strombus says goodbye and ends the call. |

---

## If something goes wrong on stage

| You see | Do this |
|---|---|
| "I couldn't reach the bank right now." | Render was asleep or Nessie is slow. Ask once more. |
| "I'm not sure that payment went through." | Nessie didn't answer in time. The payment is never sent twice; check the balance before trying again. |
| A scam stop you didn't expect | The scam check reads the whole call. Start a new call for the next scene. |
| A person is "already stopped" | Stops last until the server restarts. Use a different payee, or redeploy before the demo. |

## Rehearse it before you present

Against the built-in pretend bank (safe, nothing real moves):

```bash
docker run --rm -d --name strombus-demo -e DEMO_MODE=true -p 8000:8000 technica-backend
```
```bash
python backend/rehearse.py
```

It prints the conversation, then `40 passed, 0 failed`. Against the live server it moves real
Nessie money and leaves Bob stopped, so it asks for `--live`:

```bash
python backend/rehearse.py --url https://mcp-server-technica-2026.onrender.com --live
```
