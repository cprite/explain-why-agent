# Community Moderation Guide

Folder: Community and Support · updated 2026-10-13

# Community Moderation Guide

**OPEN AGENT HACKATHON 2026 | Build an agent that does real work**
**Internal guide for moderators on HackOS**

---

## 1. Purpose

This guide defines how moderators keep the Open Agent Hackathon community healthy, focused, safe and useful across:

- HackOS channels: Announcements, #help desk, the sponsor Help channels and team-finding
- Sponsor folders in Resources
- Mentor office hours
- Participant onboarding, 21 October
- Sponsor workshops
- The results call, 6 November
- The community on Discord after the event

Moderators create a space where participants can ask for help, form teams, debug and build, without harassment, spam, misinformation, unsafe sharing or unfair advantage.

This is a public, global event across every time zone, with a 144-hour build window. That shapes everything below: volume spikes, coverage gaps are real, and participants come from thousands of different contexts.

---

## 2. Principles

### 2.1 Be fast, clear and fair

Respond quickly. Apply rules the same way to a first-time student and a senior engineer. Don't argue publicly: clarify, redirect or escalate.

### 2.2 Keep the community useful

Move questions to the right channel. Cut duplicates by linking to official resources. Push for complete support requests with errors, logs and snippets. Keep Announcements authoritative.

### 2.3 Protect participants

Never let API keys, credentials, personal data or confidential material stay up. Escalate harassment, discrimination and threats immediately. Escalate leaked credentials and unsafe technical activity immediately.

### 2.4 Preserve fairness

Don't give one team a private advantage others don't have. Anything that affects eligibility, submission interpretation, deadlines or judging goes through the organizers and gets published publicly. Don't debug, write or materially improve anyone's submission.

---

## 3. Scope

### 3.1 HackOS

| Area | Purpose | Owner |
|---|---|---|
| **Announcements** | Official updates, read-only | Organizers |
| **#help desk** | General technical questions | Technical team + moderators |
| **Sponsor Help channels** | Help Zetaris, Help Meterless, Help Cursor, Help NVIDIA | Sponsor teams + moderators |
| **Sponsor folders in Resources** | Sponsor docs, setup, recordings | Sponsor teams |
| **Challenge pages** | Track statements and requirements | Organizers |
| **Mentor office hours** | Agent design, frameworks, debugging | Mentors |
| **Team-finding** | Forming and joining teams | Moderators |

### 3.2 Live sessions

Moderation applies to sponsor workshops, participant onboarding on 21 October, mentor office hours and the results call: chat, Q&A, reactions, and any participant behaviour other attendees can see.

### 3.3 Direct messages

Use DMs to ask someone to remove sensitive content, clarify a support request, warn about conduct, or move a sensitive report to a private path.

Do **not** use DMs for private eligibility interpretations, private deadline exceptions, private judging advice, or technical help that materially benefits one team.

---

## 4. Roles

### 4.1 Lead moderator

Assigns coverage, keeps response times on target, maintains the incident log, escalates to organizers, and approves any clarification that affects rules, submissions, eligibility or judging before it's published.

### 4.2 Channel moderator

Monitors #help desk, the sponsor Help channels and team-finding; answers or routes questions, enforces posting rules, removes prohibited content, flags repeated questions for the FAQ, and escalates by severity.

### 4.3 Mentor

Helps participants understand the tracks, navigate HackOS and the sponsor technologies, and get unstuck. Triages technical issues to the right place: sponsor, provider, framework or submission format.

Mentors do not write participant code, design a team's architecture or debug a full private repository.

### 4.4 Session moderator

Runs chat and Q&A during live sessions: groups duplicates, removes unsafe content, routes questions to the right speaker, captures what went unanswered, and manages disruptive attendees.

---

## 5. Coverage and Response Times

All times **UTC**.

### 5.1 Coverage

| Period | Dates | Coverage |
|---|---|---|
| Pre-event | To 20 October | Business hours |
| Data Day workshop | 12 October | Live during the session |
| Build Day and Power Day workshops | Dates announced on HackOS | Live during sessions |
| Onboarding | 21 October, 12:00–13:30 | Live during the session |
| Build window | 22 October, 00:00 – 27 October, 23:45 | Daily active monitoring, rota across time zones |
| Registration close | 22 October, 23:45 | Watch for late-registration questions |
| Submission day | 27 October to 23:45 | Extended coverage for submission blockers |
| Judging | 28 October – 6 November | Monitoring for clarification requests |
| Results | 6 November, 16:00 | Live during the call |

**Coverage across time zones is the hard part.** A global event means 3am questions. Set an explicit rota and publish expected response windows so participants aren't waiting on silence.

### 5.2 Targets

| Severity | Example | First response | Escalate within |
|---|---|---|---|
| **S0 — Safety or security** | Threat, harassment, leaked key, sensitive data exposure, live disruption | Immediate, within 5 minutes | 15 minutes |
| **S1 — High event risk** | Eligibility dispute, contradictory official info, deadline confusion, platform outage | 15 minutes | 30 minutes |
| **S2 — Blocker affecting many** | Sponsor service down, HackOS failure, submission form broken | 30 minutes | 1 hour |
| **S3 — Standard support** | Docker error, track question, team formation | 4 hours | 1 day |
| **S4 — Low or duplicate** | Repeat FAQ question, general chat | 1 day | Link and consolidate |

### 5.3 Submission day

On 27 October, submission blockers take priority until 23:45. In order:

1. Submission access or form failures
2. Repository link problems, including repositories still set to private
3. Demo video and slide deck problems
4. Required-component questions
5. Everything else

**Do not grant extensions.** Only the organizers can, and only through an official announcement.

---

## 6. Rules to Enforce

### 6.1 Respect

Professional communication, no insults, harassment, discrimination or personal attacks, and respect for differences in experience, language fluency and background.

Many participants are writing in their second or third language. Read generously, and don't let anyone be mocked for their English or their skill level.

### 6.2 No secrets

Participants must never post API keys, `.env` files with real values, tokens, passwords, credentials, personal data or screenshots exposing any of these.

Terminal screenshots leak keys more than anything else. Scan them.

When it happens, act under the protocol in section 10.

### 6.3 No unfair assistance

**Not allowed:** writing participant code, designing a team's architecture, producing submission-ready content for one team, private judging advice, end-to-end private repo debugging, exceptions to requirements or deadlines.

**Allowed:** explaining published rules, linking to official guides, identifying error categories, general debugging approaches, clarifying setup, clarifying submission structure, explaining published examples.

The test: would you be willing to give this same help to every team that asked? If not, don't give it.

### 6.4 No misinformation

Correct or remove posts that get the deadline, required components, sponsor technology requirements, team rules, judging process or disqualification rules wrong.

Use neutral language:

> "Thanks for helping. To avoid confusion, the official position is: [rule]. See [link]."

### 6.5 No spam

No repeated identical posts across channels, unrelated promotion, excessive tagging of organizers, thread hijacking or unapproved bot posting.

### 6.6 No unsafe technical activity

No requests for credential bypass, API abuse, rate-limit evasion or unauthorised access. No instructions for attacking HackOS, the sponsors, participants or third parties. No malware or exploit code.

Security-flavoured builds must stay defensive, dataset-based and authorised.

---

## 7. Channel-Specific Rules

### 7.1 Announcements

Official updates only, read-only for participants, everything dated in UTC. Any rule clarification is reviewed by the organizers before posting. No speculation. Pin deadline and submission updates.

### 7.2 #help desk

**Allowed:** general technical questions, track interpretation, scope guidance, dataset questions, what counts as an agent doing real work, whether an approach is broadly aligned with the track.

**Not allowed:** approving a team's full solution, guaranteeing a score, telling a team they'll pass or fail, sharing non-public judging preferences.

Say:

> "This looks aligned with the track if you can show the agent doing real work, integrate Zetaris and Meterless, and meet the submission requirements."

Not:

> "This will definitely score well."

Anything ambiguous that affects every team goes to the organizers, gets confirmed, then gets published in Announcements.

### 7.3 Sponsor Help channels

Sponsor teams own the answers. Moderators route participants to the sponsor's folder in Resources first, then the Help channel, and back to #help desk or mentor office hours if the issue turns out to be the participant's own code.

The useful triage question: **does the sponsor's own quickstart or verification step work for you?** If yes, it's their code. If no, it's access or the service.

### 7.4 Mentor office hours

**Allowed:** general debugging advice, pointers to docs, explaining error classes, how to inspect logs, clarifying trace expectations, agent design discussion.

**Not allowed:** writing implementation code, cloning and fixing a private repo, designing a whole system, hinting at hidden evaluation tests.

Ask for minimal reproducible examples. Keep snippets generic.

### 7.5 Team-finding

Keep it to team formation. Redirect technical questions. Watch for anyone pressuring someone over roles, credit or prize splits. Remind teams to:

- Agree the split in writing before submitting
- Confirm the roster before the first submission is created, because the team locks at that point
- Use "happy to build solo" in the registration form if they're building alone

---

## 8. Severity

### S0 — Safety or security

Threats, harassment, discrimination, credentials posted publicly, sensitive personal data posted, attempted unauthorised access, severe live disruption, or a participant saying they feel unsafe.

1. Remove or hide the content immediately
2. Preserve evidence in the incident log
3. Notify the lead moderator immediately
4. Escalate within 15 minutes
5. Follow up privately only

### S1 — High event risk

Public dispute about eligibility or fairness, contradictory official information, deadline confusion affecting many, platform access failures, public accusations, repeated violations after a warning.

Acknowledge publicly, move details private, escalate to organizers, publish an approved clarification if it affects many teams.

### S2 — Blocker affecting many teams

Sponsor service outage, HackOS failure, submission form broken, a broken official resource link.

Acknowledge in the channel, collect impact details, escalate to the owner, and **post status updates at least hourly** until it's fixed or there's a workaround. During a 144-hour window, silence during an outage does more damage than the outage.

### S3 — Standard support

Individual Docker errors, setup problems, track questions, team formation. Reply, link the resource, ask for missing detail, route if needed.

### S4 — Low or duplicate

Link the existing answer, merge threads, add to the FAQ backlog if it keeps recurring.

---

## 9. Actions

Use the least restrictive action that protects the community.

| Action | When |
|---|---|
| **Public redirect** | Wrong channel, duplicate |
| **Public reminder** | Minor rule issue |
| **DM reminder** | First conduct issue, accidental sensitive detail |
| **Edit request** | Partially sensitive or unclear content |
| **Hide or remove** | Secrets, harassment, spam, misinformation, unsafe content |
| **Thread lock** | Circular argument, misinformation spiral |
| **Official correction** | Wrong rule or deadline shared |
| **Warning** | Repeated or moderate violation |
| **Temporary mute** | Continued disruption after a warning |
| **Removal from a session or channel** | Severe disruption, harassment, safety issue |
| **Escalation** | Anything affecting the event, people, safety or security |

---

## 10. Sensitive Information Protocol

### 10.1 Immediate steps

1. **Hide or delete the content immediately**
2. **Capture evidence first where possible:** screenshot, channel, timestamp in UTC, username, what type of data was exposed
3. **Notify the lead moderator**
4. **DM the participant**
5. **Escalate** based on what was exposed

### 10.2 If a credential is posted

Remove it, then DM:

> "Your message included what looked like an API key or credential, so we removed it. **Rotate the key now** — deleting the message doesn't un-leak it. Repost a redacted version if you still need help."

**Rotation is the participant's job.** For a Zetaris, Meterless or NVIDIA key, they create a new one in that service; for any other provider, only that provider can revoke it. Say so plainly and quickly. Log the incident.

### 10.3 If personal or sensitive data is posted

Remove it, then DM:

> "Your message included sensitive or personal information, so we removed it. Please repost a redacted version if you still need support."

Escalate to organizers. If the data concerns someone who isn't the poster, treat it as S0.

### 10.4 Redaction standard

Before reposting, strip: keys and tokens, email addresses not needed for support, private URLs, internal hostnames, any personal, financial, medical or legal records, and screenshots showing any of these.

---

## 11. Misinformation Protocol

### 11.1 High-risk misinformation for this event

| Wrong | Correct position |
|---|---|
| "The deadline is later than 23:45." | Submissions close **27 October, 23:45 UTC** |
| "Registration closes at 23:59." | Registration closes **22 October, 23:45 UTC** |
| "You can still register after 22 October." | No late registration |
| "Late submissions are accepted." | They are not evaluated |
| "Team size can be more than five." | Maximum five |
| "You can change your team after submitting." | The team locks when the first submission is created |
| "You must use [specific model provider]." | Model choice is open |
| "Sponsor technology is optional." | Zetaris and Meterless are required in every submission; Cursor is the required development environment; NVIDIA wherever it contributes |
| "There's a Bright Data bounty track." | There isn't. Three tracks plus Wildcard [Tinkerer] |
| "Your repository can stay private." | It must be public |
| "The demo can be any length." | 1–4 minutes |
| "A slide deck is optional." | It's a required component |
| "A fixed A → B → C chain is fine." | Judges look for real collaboration |
| "A demo video can replace a working project." | It can't |
| "Hardcoded outputs are fine for the demo." | They are a disqualification risk |
| "Old code is fine without declaring it." | Pre-existing work must be declared |
| "Judges will install missing dependencies for you." | They won't |
| "There's a 30-point bonus." | The rubric totals 100 |

### 11.2 Correction template

> **Moderator clarification:** the official position is: [rule]. See [link]. We've removed conflicting guidance to keep the channel accurate.

### 11.3 Approval required

Get organizer approval before posting anything about deadlines or exceptions, eligibility, prize terms, judging process changes, or disqualification interpretation.

---

## 12. Team Disputes

### 12.1 Common issues

Someone wants to leave, a team wants to remove someone, disagreement over an idea, an inactive member, conflict over submission ownership, hostile communication, **and above all, arguments about the prize split.**

### 12.2 Response

Minor:

> "Please keep it professional. For team changes, use team-finding on HackOS and confirm with everyone affected. Remember the team locks when your first submission is created."

A dispute:

> "This is a team governance issue. We're escalating to the organizers. Please pause the public discussion until they've reviewed it."

### 12.3 Prize splits

Cash prizes are split equally among team members unless the team submits a different split in writing.

Moderators should push this early and often during team formation, because it's far easier to settle on 22 October than on 6 November when there's money on the table.

### 12.4 Boundaries

Moderators must not decide who owns an idea, remove team members outside the approved process, publicly blame anyone, or promise that a dispute will affect judging.

---

## 13. Live Session Moderation

### 13.1 Before the session

| Task | Owner | Status |
|---|---|---|
| Confirm link and moderator access | Lead moderator | ☐ |
| Confirm host, co-hosts, speakers | Lead moderator | ☐ |
| Confirm chat and Q&A settings | Session moderator | ☐ |
| Prepare the pinned welcome message | Session moderator | ☐ |
| Prepare resource links | Channel moderator | ☐ |
| Set up the escalation backchannel | Lead moderator | ☐ |
| Confirm who can remove attendees | Host | ☐ |
| Confirm the recording policy | Organizers | ☐ |
| Confirm participants can access the session without paying | Organizers | ☐ |

### 13.2 Settings

Moderated Q&A on. Attendees muted by default. Screen sharing limited to presenters. Attendee file uploads off. Anonymous posting off. Chat open only while actively moderated.

### 13.3 Pinned welcome

> Welcome to the Open Agent Hackathon. Keep the chat professional and use Q&A for questions. Do not post API keys, credentials or personal data. For support during the event, use the #help desk channel, the sponsor Help channels, or mentor office hours on HackOS.

### 13.4 Q&A

Group duplicates, prioritise questions affecting everyone, route to the right speaker, never read out a question containing private information, rephrase hostile questions neutrally, and capture the unanswered ones for follow-up.

Priority order: platform access, track selection, sponsor setup, team formation, build expectations, submission requirements, judging, prizes.

### 13.5 Disruption

| Behaviour | First action | Then |
|---|---|---|
| Off-topic repetition | Public reminder | Disable that participant's chat |
| Spam | Remove posts | Remove attendee |
| Harassment or abuse | Remove content immediately | Remove attendee and escalate |
| Credentials or sensitive data | Remove immediately | Section 10 protocol |
| Hostile challenge to a speaker | Rephrase or defer | Private follow-up |
| Unauthorised sharing or audio | Stop and mute | Remove attendee |

Remove an attendee immediately for threats, harassment, discriminatory language, malicious links, repeated sensitive posting, or repeatedly ignoring moderators. Log every removal.

### 13.6 After the session

Within 24 hours: publish the recording on HackOS if approved, publish resources, post answers to common questions, open follow-up threads for unresolved issues, log incidents, and review gaps before the next session.

---

## 14. Response Templates

**Wrong channel**

> Thanks. This belongs in [channel], where the right people can help. Please repost with the error message and any relevant snippet, secrets removed.

**Duplicate**

> Answered here: [link]. Closing duplicates to keep the channel readable.

**Missing detail**

> Happy to help, but we need a few things first:
> - What command did you run?
> - What's the exact error?
> - Framework and model provider?
> - Local or Docker?
> - What have you already tried?

**Credential posted**

> We removed your message because it included what looked like a key or credential. **Rotate that key now** — deleting the message doesn't protect it. Repost a redacted version if you still need help.

**Conduct reminder**

> Moderator reminder: keep it respectful and on the issue. Critique the approach, not the person.

**Heated thread**

> Pausing this thread. The moderation team will review and follow up if an official clarification is needed.

**Clarification pending**

> This affects official interpretation, so we're confirming with the organizers before answering. Please wait for the moderator-confirmed response.

**Deadline or exception request**

> Extensions are decided by the organizers, not moderators. Unless an official announcement says otherwise, the deadline remains **27 October, 23:45 UTC**.

**Sponsor technology requirement**

> Zetaris and Meterless are required in every submission, including Wildcard [Tinkerer]. Cursor is the required development environment, and NVIDIA should be used wherever it contributes. Setup is in each sponsor's folder in Resources.

**Provider error**

> Check whether a minimal SDK call works outside your framework. If it fails on Meterless or NVIDIA, ask in that sponsor's Help channel. For any other provider, their support will be faster than we can be. If the minimal call works but your framework doesn't, bring it to mentor office hours.

**Sponsor service**

> Please check [sponsor]'s folder in Resources on HackOS first, then ask in Help [sponsor]. If their own quickstart works for you but your code doesn't, bring it to #help desk or mentor office hours with the error.

**Full repo debugging request**

> We can't debug a whole repository, but we can help with a specific reproducible error. Share the command, the error, the relevant snippet and your environment, secrets removed.

---

## 15. Incident Logging

Log every S0 and S1, and repeated S2s.

```text
Incident ID:
Date/time reported (UTC):
Reported by:
Channel or session:
Participants involved:
Severity: S0 / S1 / S2 / S3 / S4
Category: Conduct / Security / Sponsor / Submission / Platform / Session / Other
Summary:
Content removed? yes/no
Evidence captured? yes/no
Immediate action:
Escalated to:
Escalation time (UTC):
Status:
Follow-up owner:
Resolution:
FAQ update needed?
```

Evidence stays in approved internal locations, shared only with escalation owners, redacted where possible, never reposted publicly.

Collect the minimum needed. Never ask someone to publicly share private personal, medical, legal or financial details.

---

## 16. Decision Tree

**1. Is there immediate harm or exposure?**
Remove, preserve evidence, escalate as S0. (Harassment, credentials, sensitive data, malicious links.)

**2. Is this an official event decision?**
Don't answer definitively. Escalate to organizers. Publish only the approved answer. (Eligibility, deadlines, exceptions, prize terms.)

**3. Is this a conduct issue?**
Move it private. Escalate. No public investigation.

**4. Is this a technical platform issue?**
Sponsor service → the sponsor's folder and Help channel, then sponsor support.
HackOS or GenAI Academy → HackOS escalations.
Non-sponsor model provider → the participant's own provider.
Submission format → Official Rules, then organizers if genuinely ambiguous.

**5. Is this normal support?**
Answer, link the resource, ask for what's missing, route if needed.

---

## 17. Fairness Rules

### 17.1 No private advantage

No custom architecture reviews, full repo reviews, score predictions, hidden criteria, code, private extensions or private exceptions.

### 17.2 Publish general guidance

If a clarification helps more than one team, post it publicly once approved.

### 17.3 Link to published resources

Welcome Guide, Official Rules, Submission Requirements, Technical Execution Guide, FAQ, Troubleshooting Guide, Help Desk Guide, and the sponsor folders in Resources.

### 17.4 Avoid judging language

**Don't say:** "This will win." "This will pass." "Judges will like this." "Pick this track, it's easier to win."

**Do say:** "This looks aligned with the published requirements." "Judges score against the published rubric." "The official position is…"

---

## 18. Scenarios

**A key is posted publicly**
Remove, DM with rotation instructions, log it, escalate if the exposure was significant or the key isn't theirs.

**Someone says a specific model provider is required**
Correct publicly: model choice is open. Zetaris and Meterless integration is what's required. Link the rules.

**Someone says sponsor technology is optional**
Correct publicly: Zetaris and Meterless are required in every submission, Cursor is the required development environment, and NVIDIA should be used wherever it contributes. Link the rules.

**Someone asks about the Bright Data bounty**
Correct publicly: there is no Bright Data track. The tracks are the three challenge tracks plus Wildcard [Tinkerer].

**A public complaint about eligibility**
Acknowledge, don't discuss anyone's eligibility publicly, escalate, move private.

**Teammates argue publicly**
Conduct reminder, ask them to pause, escalate. If it's about the prize split, point at the default equal split and the need for a written agreement.

**A team wants to change its roster after submitting**
Explain that the team locked when the first submission was created. Escalate to organizers only if it's an obvious administrative error.

**Q&A flooded with duplicates**
Pin an answer, group in Q&A, say duplicates are being consolidated, publish a follow-up FAQ.

**Extension request**
Don't approve. State the deadline. Escalate only if there's a platform problem.

**Full repo debugging request**
Decline, ask for a minimal reproducible error, point at the Troubleshooting Guide.

**A sponsor or provider outage mid-build**
Escalate to the sponsor through its Help channel and post hourly updates. Remind teams that sample mode keeps a project demonstrable when a service is down, and that judges need it too.

---

## 19. Checklists

### Daily during the build window

- [ ] Review every channel
- [ ] Clear unanswered S1 and S2 items
- [ ] Scan for leaked secrets, including in screenshots
- [ ] Move misplaced questions
- [ ] Flag repeated questions for the FAQ
- [ ] Check no clarification request is sitting unanswered
- [ ] Review the incident log
- [ ] Hand over to the next time zone with open items noted

### Submission day, 27 October

- [ ] Pin the submission checklist and the deadline
- [ ] Remind teams that repositories must be public
- [ ] Monitor submission issues continuously
- [ ] Escalate platform failures immediately
- [ ] Correct deadline misinformation instantly
- [ ] Watch for keys in last-minute screenshots
- [ ] Log every exception request, approve none
- [ ] Publish approved clarifications publicly

### Live session day

- [ ] Confirm roles and the escalation backchannel
- [ ] Confirm participants can join without paying
- [ ] Pin the welcome and conduct message
- [ ] Monitor Q&A continuously
- [ ] Remove unsafe content immediately
- [ ] Capture unanswered questions
- [ ] Log incidents
- [ ] Publish follow-ups within 24 hours

---

## 20. Escalation Owners

| Escalate to | For |
|---|---|
| **Organizers** | Event decisions, deadlines, eligibility, prizes, official announcements, conduct, anything affecting many teams |
| **HackOS escalations** | HackOS and GenAI Academy platform failures, access problems |
| **Sponsor support** | A sponsor service down, credentials or credits not provisioning, platform-level errors |
| **The participant's own provider** | Auth, rate limits, billing on a non-sponsor provider |
| **Organizers, privately** | Exposed credentials, sensitive data, security or safety concerns |

| Role | Name | Contact |
|---|---|---|
| Lead moderator | Isreal | @isreal |
| Organizer escalation | GenAI Works organizing team | hackathons@genai.works |
| Conduct and safety escalation | GenAI Works organizing team | hackathons@genai.works |
| Platform escalation | HackOS escalations | HackOS escalations |
| Zetaris support | Zetaris team | Help Zetaris channel |
| Meterless support | Meterless team | Help Meterless channel |
| Cursor support | Space XAI and Cursor team | Help Cursor channel |
| NVIDIA support | NVIDIA team | Help NVIDIA channel |

---

## 21. Final Guidance

Moderation is enablement, not just enforcement.

A strong moderator keeps the space respectful, protects credentials and private data, routes questions to the right expert, avoids creating unfair advantage, turns repeated confusion into public guidance, and escalates early rather than improvising.

When unsure:

1. **Pause.**
2. **Don't guess.**
3. **Acknowledge the participant.**
4. **Escalate to the right owner.**
5. **Publish the confirmed answer publicly if it affects more than one team.**
