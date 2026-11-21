# job_searcher

A job-search pipeline for senior roles, run by an AI agent under written rules.

**Version 1.02, 2026-11-21**

## Description

The pipeline collects job postings, drops what breaks a hard rule, scores the rest against an anonymised profile and
gives a person a short list to decide on. It was built for a search for senior roles in IT risk, information
security and operational resilience. The field is set in settings files, so it can be changed.

The agent prepares; the person decides and sends. No script applies for a job or sends a message.

This version publishes the decision layer and the CV builder:

- the title check, the intake step, the hard filters, the fit scoring, the bands and the decision record
- the pay estimate and the "already seen" index
- a builder that writes a CV as a Word file from a content file

The scripts that collect postings from careers sites and job boards are not published yet. To try the pipeline, you
save a posting by hand in the inbox format. An example is included.

## Setup

Python 3.10 or later. Run every command from the top folder of the repository.

```
pip install -r requirements.txt
```

Copy each example file to its real name and put your own values in:

```
.env.example                    ->  .env
agent/feed_terms.example.json   ->  agent/feed_terms.json
agent/employers.example.json    ->  agent/employers.json
agent/constraints.example.json  ->  agent/constraints.json
agent/profile_jev.example.md    ->  agent/profile_jev.md
```

The real names are listed in `.gitignore`, so your own values are not committed by accident.

The only key that the code in this version needs is `JEV_API_KEY`, and only for scoring. Without a key, the title check, the
intake step, the hard filters, the dry run and the CV builder all work.

A quick check that the setup is complete:

```
python agent/scripts/feed_terms.py --check "Head of IT Risk"
python agent/scripts/jev_score.py --jd examples/inbox_item.example.md --dry-run --no-write
python agent/scripts/build_cv_format.py --content examples/cv_content.example.json --out cv.docx
```

## Process

The search runs in seven steps. Step 0 runs all the time, step 1 is built once and then kept current, and steps 2
to 6 run for each role.

| Step | Name | What happens | Who does it | Code in this version |
|---|---|---|---|---|
| 0 | Positioning and network | Public writing in the field, a list of target employers, a map of contacts | The agent researches and drafts; the person publishes and makes contact | none |
| 1 | Profile | One profile with every preference marked hard or soft, and a copy without identity for the scorer | The person answers; the agent compiles | example files |
| 2 | Feed | Postings are collected, checked against what was seen before, and saved as text snapshots | Scripts, started by the agent on request | `seen_index.py`, `intake.py`; the collectors are not published |
| 3 | Decision | Title check, hard filters, one scoring call, a band of Go, Stretch or No, and a decision record | Scripts; the person decides every Stretch | `feed_terms.py`, `jev_score.py`, `pay_estimate.py` |
| 4 | Package | A tailored CV, a recommended channel and draft texts for one role | The agent drafts; the person edits, decides and sends | `build_cv_format.py` |
| 5 | Monitoring and learning | The tracker is kept current and outcomes are fed back into the profile and the thresholds | The agent prepares; the person acts | the decision log written in step 3 |
| 6 | Interview and offer | A briefing on the employer and preparation for the conversation | The agent prepares; the person holds the conversation | none, planned |

## How to run each step

A step without a script is run by asking the agent. Each such step below says what you ask for, what you get and
what stays with you.

### Step 0: Positioning and network

No script.

- **You ask** for research on an employer on your target list, or for a draft of a public post in your field.
- **You get** an entry in the target list or a draft text, saved in the workspace.
- **Stays with you:** editing, publishing and every contact with a person.

### Step 1: Profile

No script. The result is three files.

- **You ask** to be interviewed for the profile: your situation, skills with evidence, places, sectors and
  conditions, each preference marked hard or soft.
- **You get** the full profile (private), `agent/profile_jev.md` (the profile without name, contacts and employer
  names, which is the only description of you that the scorer receives) and `agent/constraints.json` (the hard
  rules, which are checked locally and never sent).
- **Stays with you:** every answer. The agent records facts and does not invent them.

In this version you start from the example files copied during setup and edit them by hand.

### Step 2: Feed

The collectors are not published in this version. Save a posting by hand instead:

1. Copy `examples/inbox_item.example.md` to `agent/inbox/<date>_<company>_<title>.md`.
2. Fill in the facts at the top, set `status: live` and paste the text of the posting below.

Two helpers of this step are included:

```
python agent/scripts/intake.py --check "Zurich, ZH, Switzerland"
python agent/scripts/intake.py --employer "Deutsche Bank AG"
python agent/scripts/seen_index.py
python agent/scripts/seen_index.py --check "<company>" "<title>" "<city>"
```

The first two show how a place is read into country and city and how an employer is looked up in
`agent/employers.json`. The last two print the size of the index built from `agent/inbox/` and tell you whether a
role was seen before.

### Step 3: Decision

```
python agent/scripts/feed_terms.py --check "<title>"
python agent/scripts/jev_score.py --jd agent/inbox/<item>.md --dry-run --no-write
python agent/scripts/jev_score.py --ping
python agent/scripts/jev_score.py --jd agent/inbox/<item>.md
python agent/scripts/pay_estimate.py agent/inbox/<item>.md
```

1. The title check says whether the title passes the level rule, the subject list and the exclusions.
2. The dry run applies the hard filters and prints the request that would be sent. Nothing is sent or written.
3. The ping makes one small call to confirm that the key works.
4. The scoring run prints one line with the band and the probabilities, writes a `## Decision` block into the item
   and adds one line to `agent/inbox/_log.jsonl`.
5. The pay estimate reads the posting and says whether the pay is likely below your walk-away figure.

To score one item despite a hard filter, add `--override "<reason>"`. The waived rule and the reason are recorded
in the decision.

**Stays with you:** every Stretch, and every override.

### Step 4: Package

```
python agent/scripts/build_cv_format.py --content <content file>.json --check
python agent/scripts/build_cv_format.py --content <content file>.json --out cv.docx
python agent/scripts/build_cv_format.py --content <content file>.json --out cv.docx --layout relaxed
```

A content file holds wording only. The structure is fixed in the script: the parts and their order, four highlight
lines, three competency lines, at most six bullets for a role, and the form of the dates. A content file that adds,
drops or reshapes a part is refused with the list of what is wrong. The script writes the Word file; the PDF is
exported from Word, and the page count is checked there.

The rest of the step has no script.

- **You ask** for a copy of your content file tailored to one role, and for draft texts for that role.
- **You get** the content file, the built CV and the drafts in the folder of that employer.
- **Stays with you:** reading, editing and sending. Tailoring changes wording, order and emphasis. It adds no fact
  that is not in your own content file.

### Step 5: Monitoring and learning

No script in this version.

- **You ask** for a review of the pipeline.
- **You get** an updated tracker, the stage at which roles are being lost, and proposals for the profile and the
  thresholds based on the outcomes so far.
- **Stays with you:** every follow-up with a person, and the decision to change a threshold.

The data for this step is the decision log: one line for each scored item in `agent/inbox/_log.jsonl`.

### Step 6: Interview and offer

Planned, no script.

- **You ask** for a briefing on the employer and for likely questions for the role.
- **You get** a briefing file and a bank of your own stories to draw on.
- **Stays with you:** the conversation and the negotiation.

## How it works

**The inbox item.** Each posting is one text file: the facts on top (company, title, place, country, sector,
contract type, pay if published, status) and the text of the posting below.

**The capture gate.** The scorer refuses an item unless its status is `live` and it has at least 120 words of
running text. Only lines of twelve words or more count; list lines and headings do not. A scoring model that is
given an error page or an expired posting still returns confident numbers, so such pages are stopped before the
call.

**Intake.** Missing facts are filled from the posting: company, place, country, sector and company type. A country
that cannot be found is written as unknown. It is never guessed.

**Hard filters.** They run locally, in this order, and the first miss ends the run with the band No and the name of
the rule:

1. the place is on the excluded list
2. the sector, the company type or the employer is on an excluded list
3. the published pay is below the minimum for that place, or a project's rate or length is below the minimum
4. the posting refuses visa sponsorship for a place where the candidate would need it

No model call is made for a role that fails a hard filter.

**Scoring.** One call sends the anonymised profile, the facts and the text of the posting, with seven typed
questions: realistic match, likely to reach an interview, seniority fit, kind of work, fit to soft preferences, pay
against the candidate's floor, and the main gap. The model answers yes-or-no questions with a probability and
choice questions with a probability for each option. It writes no prose.

**Bands.** The probabilities become Go, Stretch or No. The lines are in `THRESHOLDS` at the top of `jev_score.py`:

- A match of 0.65 or more is a Go and a match below 0.35 is a No. Between the two it is a Stretch. For places of
  second priority and for an unknown place the Go line is 0.70.
- A weak interview or seniority answer, a preference miss or pay below the floor lowers the band, by one step at
  most in total.
- Work of a kind the candidate has ruled out is a No.
- For places of third priority a Go becomes a Stretch, and places outside the priorities reach at most Stretch.
- After that, a Stretch with a personal contact at the employer is promoted to Go from a match of 0.60.

**The decision record.** The band, the probabilities, the rules that fired, the model version, the usage and any
override are written into the item and into the log. The thresholds are tuned from that log.

**The pay estimate.** For a posting without published pay, a rough estimate is made from the title, the years of
experience asked for, the type of employer and the place. No outside call is made. An estimate below the walk-away
figure moves a Go to Stretch. It never drops a role.

## External services

Two levels are shown. **Necessary** is the least the agent needs to run the process from feed to decision. **Best
performance** is everything the pipeline uses when it runs at full quality.

| Service | Step | Used for | What it receives | Necessary | Best performance |
|---|---|---|---|---|---|
| Claude Code by Anthropic | all | The agent that runs the steps under the control document | The files of the workspace it works on | Yes | Yes |
| JEV by TypeSafe | 3 | Fit scoring: probabilities for typed questions | The profile without identity, and the facts and text of the posting | Yes | Yes |
| Jina Reader | 2 | Turns the page of a posting, or a page of an employer's careers site, into text | The link of the page | Yes | Yes |
| Tavily | 2 | Finds the employer's own posting for a role that was found on a job board, so that the original is read and scored as well | Search terms: the company name and the title | No | Yes |
| Exa | 3 | Research on an employer for a role already marked Go or Stretch | Company and role names and, for a single role, the name of a person in a public role there. Never lists of people | No | Yes |
| Perplexity | 6 | Briefing on an employer before a conversation | Company and role names | No | Yes. Planned, not used so far |
| Apify | 2 | Fallback for a job board that cannot be read plainly. Public postings only | The link of a public posting | No | Only as a fallback. Not used so far |

What the necessary three give: without Claude Code there is no agent, without Jina Reader postings on employer
sites cannot be captured, and without JEV there are hard filters but no fit score.

What the others add: without Tavily a role found on a job board is scored from the board's copy only. Without Exa,
research on an employer rests on plain web search. Without the search key the run goes on and skips that step.

The code published in this version calls only JEV. Jina Reader and Tavily are called by the collectors, which are
not published yet, and Exa and Perplexity are called by the agent. The scripts read `JEV_API_KEY`, `JINA_API_KEY`
and `TAVILY_API_KEY` from `.env`.

One local program is used as well: Microsoft Word exports the built CV to PDF. Nothing leaves the machine, and any
program that turns a Word file into a PDF will do.

Calls to the reader and the search service are counted per day, and the scorer's usage is recorded with each
decision, so the monthly cost can be checked against a budget.

## Rules built into the code

- The candidate's identity stays on the machine. The scorer receives a profile without name, contacts or employer
  names.
- Hard constraints are applied before the model call and are never sent.
- The scripts only read. The agent drafts; a person edits, decides and sends.
- A dead or thin page is not scored, and an unknown place is not guessed.
- An override applies to one item and is recorded with the rule that was waived.
- API keys are read from a local `.env` file and are never printed.
- The structure of the CV is locked in code. Tailoring changes wording only.

## What is in the repository, and what is not

| File | What it does |
|---|---|
| `agent/scripts/intake.py` | Fills in company, place, country, sector and company type for a posting. An unknown country stays "location unknown" and is never guessed. |
| `agent/scripts/feed_terms.py` | The title check: level rule, subject list and exclusions, read from `feed_terms.json`. |
| `agent/scripts/pay_estimate.py` | A free, rough pay estimate from the posting text. "Likely below walk-away" moves a Go to Stretch; it never drops a role. |
| `agent/scripts/jev_score.py` | Hard filters, one scoring call, band mapping, the decision block in the item and the decision log. |
| `agent/scripts/seen_index.py` | The "already seen" index: same link, or same company, title and city. One employer under two names counts as one. |
| `agent/scripts/usage.py` | Counts reader and search calls for the monthly budget. |
| `agent/scripts/net.py` | Keeps Windows awake during a run and waits for the network after a dropout. |
| `agent/scripts/build_cv_format.py` | Builds a CV as a Word file from a content file. The structure is fixed in the script; a content file that changes it is refused. |
| `agent/*.example.json`, `agent/profile_jev.example.md` | Example settings and a fictional profile. |
| `examples/inbox_item.example.md` | A fictional posting in the form the scorer reads. |
| `examples/cv_content.example.json` | A fictional content file for the CV builder. |

Not in the repository:

- **The collectors.** The scripts that read careers sites and job boards, and the script that writes the
  digest, are not published yet. Code that reads a site is published only after that site's terms of use
  have been checked.
- **Personal data.** The profile, the CV text, the real settings, the captured postings, the application
  tracker and the control document stay private.

## Release notes

Numbering: the second decimal changes for fixes (1.01), the first decimal for new parts (1.10), and the number
before the point for a change in how decisions are made (2.00).

### 1.02, 2026-11-21

The table of external services now has the columns "Necessary" and "Best performance". Necessary are Claude
Code, JEV and Jina Reader; the other services add quality and the pipeline runs without them. Microsoft Word is
described below the table, because it is a local program and not an external service. No published code changed.

### 1.01, 2026-11-21

The table of external services is corrected. It now shows in two columns what the full pipeline uses and what
the code published here calls. The table in 1.00 had one column, "Needed by 1.00", which could be read as if the
reader and the search service were not in use. Both are in regular use in the full pipeline. No code changed.

### 1.00, 2026-11-21

First public version.

Contains:

- the decision layer: title check, intake, hard filters, scoring, bands, decision record, pay estimate, seen index
- the CV builder
- example settings, a fictional profile, a fictional posting and a fictional CV content file

Known limits:

- Collection is not published. Postings are saved by hand in the inbox format.
- Scoring needs a paid key for JEV. Without it the pipeline runs up to the dry run.
- The thresholds were tuned by hand on a small number of roles. Treat them as starting values.
- The title lists, the level rule and the exclusions in the example settings are written for IT risk and security
  roles, in English and German.
- The CV builder produces one fixed layout and does not check the page count. The PDF export goes through Word.
- `net.py`, a helper for long runs, keeps the machine awake on Windows only.

## License

MIT, see [LICENSE](LICENSE). Maintained by second-line-labs.
