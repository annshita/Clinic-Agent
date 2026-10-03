cat > DECISIONS.md <<'EOF'
# DECISIONS

Format: **Found** / **Chose** / **Why**.

## A. Problems in the material given

1. **Overlapping window.** Found: Dr. Rao's Monday windows overlap (09:00-12:00 and 11:45-15:00). Chose: merge them into one set of 15-minute slots. Why: slots must not appear twice, and the 11:45 start still lies on the 15-minute grid.
2. **"Two windows per day" is not true.** Found: the brief says two windows per day each, but Rao's Saturday and Sethi's Wednesday and Saturday have one, and Rao's Monday has overlapping windows. Chose: trust `clinic.json`. Why: the data is what the tools check against.
3. **Shared identity data.** Found: Aarav and Arjun Gupta share phone and date of birth, and Sunita Gupta shares that phone too. Chose: a phone alone is never enough to pick a patient. Why: the first name is the only separator, and guessing is a wrong answer.
4. **Forward guardian reference.** Found: pt_0009 (Meera) is guardian of pt_0031 (Kabir), who is defined later in the list. Chose: resolve guardianship by id at runtime, not by list order. Why: the data is valid but order-dependent code would break.
5. **Near-duplicate names.** Found: Imran Qureshi and Imraan Quraishi, and the three Sharmas. Chose: a name-only lookup returns every close match, and a phone number settles it. Why: the tool must return candidates, never a guess.
6. **No tool returns appointments.** Found: cancel and reschedule need an appointment id, but none of the six tools exposes one. Chose: `lookup_patient` returns each candidate's upcoming booked appointments. Why: every id the agent uses still comes from a tool result.
7. **"kal" is ambiguous.** Found: it can mean yesterday or tomorrow. Chose: tomorrow. Why: appointments are never in the past, and the tool rejects past dates.

## B. Behaviour choices

8. **Clinical urgency runs first.** Chest pain, breathing trouble and similar phrases escalate as `clinical_urgent` before any other logic, whatever came earlier in the call. Why: this is the brief's hard rule.
9. **Over-escalation on symptom words.** Negated symptoms ("no chest pain") and past-tense mentions escalate too. Why: a missed emergency costs far more than one extra handoff.
10. **Mild symptoms are not escalated.** "Halka bukhar hai, appointment chahiye" just books. Why: restraint is scored. Only urgent signs, or a question about medicine or a diagnosis, escalate.
11. **Writes happen after all turns are read.** The script is fixed, so the agent collects every turn first and then acts once. Why: a late correction or an emergency in turn 3 can never leave a half-made booking.
12. **Corrections.** Within a turn, text after "nahi nahi", "actually" and similar wins. Across turns, the latest date or time wins.
13. **Weekday vs date conflict.** "Saturday 5 tareekh" gives `abandoned`, with a request for the right date. Why: either choice would be an invented guess.
14. **No time given.** The agent asks, and the call ends `abandoned` if nobody answers. A day-part ("subah") books the earliest free slot in that part. Why: an exact hour is never invented, but a stated preference is honoured.
15. **Requested time unavailable.** The agent lists slots from the tool and does not book. Why: the caller never confirmed another slot.
16. **Authorisation.** The caller must be the patient or a listed guardian. Someone acting for another person, or an unidentified caller calling themselves a neighbour or friend, escalates as `not_authorised`. The tool layer enforces this independently of the agent.
17. **Unknown patient or wrong phone.** `abandoned` with a request to re-check. Why: no tool exists to register patients, and it needs no human.
18. **Injection and bulk requests.** Turns containing them are ignored. If nothing legitimate is left, the state is `refused`. If a real request remains, it is handled. Why: nothing here needs a human, and the legitimate part should not be punished.
19. **Out of scope.** Billing, reports, certificates and similar requests escalate as `out_of_scope` unless there is also a booking request.
20. **Determinism.** The agent is rule-based, with no LLM and no randomness. Why: the brief scores the worst of three runs, and predictability counts for more than fluency.

## C. Known limits

- Hindi, English and Hinglish phrases outside my word lists are missed.
- Devanagari support is minimal.
- Same-weekday dates ("Thursday" said on a Thursday) resolve to next week.
- Phone numbers must be 10 digits in one piece.