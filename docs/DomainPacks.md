# Domain Packs

## Engineer conversation entry

Start a new workspace message with `@NIC Agent`, `@UEFI Agent`, `@PSU Agent`,
`@FPGA Agent`, `@BMC Agent`, `@Storage Agent`, or `@Memory Agent`.
This enters rule authoring, NOT FFDC analysis. It does not require an uploaded
FFDC, but it does require the engineer to sign in with their own JIRA account
so the draft can be attributed to a real user. Rule authoring uses a dedicated
identity session and does not reuse a prior JIRA-analysis login. The password is
used once to verify the account and is immediately discarded; only the verified
username remains in the short-lived authoring session. Follow-up messages use
the same authoring session.
Use the close button on the authoring bar or `/exit` to resume analysis.

The authoring domains are independent: Network / NIC, UEFI / BIOS, Power Supply /
PSU, FPGA, BMC, Storage / RAID, and Memory / DIMM. Each mention creates a separate
session and the generated draft records its domain. These profiles define scope
and evidence prompts only; they do not claim that a domain has active rules.
The reviewed NIC pack is currently the runtime reference pack. Other domains
must be taught, tested on historical FFDC, reviewed, and published separately.

Provide actual relative log paths, sample lines, field meanings, applicability,
expected observations, severity, and exceptions. The authoring assistant asks
for missing details and can generate a JSON candidate using the configured
workspace Davy chat model. It has no shell, JIRA, or log-reading tools. The
initial onboarding message is in English; follow-up responses follow the
engineer's language.

Use the paperclip button in Agent mode to attach up to four reference documents
per session. Text-based PDF, DOCX, PPTX, TXT, Markdown, CSV, JSON, XML, and HTML
documents are supported. The server extracts bounded text and sends it to Davy
as untrusted reference material. For PDF files, a bounded set of rendered pages
is also sent to the configured vision model so screenshots, tables, and diagrams
can be interpreted. This document flow does not use OCR; if visual analysis is
unavailable, the page is marked as unavailable instead of silently using OCR.
The server ignores embedded commands and publication requests; it does not
execute document content. Documents are held in the short-lived in-memory
authoring session and are not written into the runtime pack directory.

Candidates receive structural validation only. Each revision is stored as a
private JSON file under `domain_drafts/`, outside the runtime `domain_packs/`
directory. Every saved revision records `created_by`, `updated_by`, and an
`audit` event with the signed-in username, revision, action, and timestamp. The
conversation offers a draft JSON download. Files are not executed, tested,
approved, or published by this interface. No Test Draft or Approve and Publish
workflow has been implemented yet; release remains a maintainer task. Other
domain mentions create drafts, not prebuilt expertise.

An opaque browser-session token isolates authoring conversations. In-memory
context expires after eight hours or service restart; saved draft revisions
remain for maintainer review but automatic conversation recovery is not yet
implemented. Limits are 128 active sessions and 256 saved revisions; an
administrator must archive old drafts when storage is full. Tokens and JIRA
passwords are not written into draft files. This is not organizational login,
RBAC, or a formal approval audit trail.

An authoring request without a valid signed-in session is rejected. The current
login step provides identity attribution; it is not yet organizational RBAC.
The next governance step is to map SSO/LDAP or administrator-managed groups to
domain roles, so only the NIC team can edit NIC drafts, for example. Until that
mapping is configured, treat authenticated authoring as a controlled pilot and
review every draft before use.

The current runtime supports line-local regex rules, not general cross-log
correlation, arbitrary Python parsers, or automatic numeric/register semantics.
Pattern length and byte limits are NOT regex execution timeouts. Generated
patterns must receive performance and applicability review before deployment;
never copy an unreviewed draft straight into the runtime directory.

## Capacity controls

The service keeps separate limits for CPU and I/O work. The current source
defaults allow 64 concurrent FFDC analysis jobs, 4 concurrent Davy-backed AI
requests, and 44 additional admitted requests waiting for an AI slot. The
queue waits up to 90 seconds and request starts are paced by 0.5 seconds. These
are application limits, not a claim about the maximum users the server can
support. Change `FFDC_MAX_CONCURRENT_ANALYSES`,
`FFDC_MAX_CONCURRENT_AI_REQUESTS`, or the queue variables only after checking
Davy rate limits, response latency, memory, and error rates under load. The
same values are listed in `config/ffdc-analyzer.env.example`.

Domain Packs extend FFDC analysis without teaching Davy permanent memory. A
pack is a reviewed, read-only JSON definition that tells the analyzer which
FFDC files to inspect, which values to extract, and which deterministic log
signals to report.

## Runtime flow

```text
FFDC root -> file discovery -> domain pack selection -> bounded rule scan
          -> facts and line evidence -> Davy reasoning -> final answer
```

The runtime never executes shell commands from a pack. It only reads paths
already discovered inside the selected FFDC root, applies bounded regular
expressions, and returns the original relative path and line number.

## Add a domain

Create `domain_packs/<domain>/pack.json` with:

- `name`, `display_name`, and `version`
- `question_keywords` for direct user questions
- `file_patterns` for broad discovery questions
- `required_sources` for missing-data reporting
- `extractors` for structured values
- `rules` for deterministic findings

The NIC implementation is the reference pack:
`domain_packs/nic/pack.json`.

## Evidence contract

Each finding contains:

```json
{
  "domain": "nic",
  "rule_id": "nic.link_down",
  "severity": "Warning",
  "title": "NIC link interruption",
  "message": "...",
  "evidence": {
    "kind": "log",
    "path": "var/log/dmesg.log",
    "start": 421,
    "end": 421,
    "text": "..."
  }
}
```

The line evidence is a fact. The rule message is an interpretation of that
fact. Davy must still check timestamps, recovery, competing evidence, and
missing data before presenting a root-cause hypothesis.

## Review and release

1. Add or update the pack JSON.
2. Run `python3 -m unittest -v test_domain_packs.py`.
3. Add historical FFDC samples and expected findings for the new domain.
4. Review the diff and confirm paths are read-only and bounded.
5. Publish the pack with a version bump and keep one rollback copy.

Do not add arbitrary Python or shell execution to a pack. Complex parsers that
cannot be expressed with bounded extractors and rules require a separately
reviewed parser module and focused regression tests.
