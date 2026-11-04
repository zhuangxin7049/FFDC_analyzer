# ThinkSystem FFDC Analyzer

Analyze ThinkSystem FFDC evidence and JIRA defects through structured reports, an evidence-aware conversation workspace, and scheduled Defect Review.

## Quick Start

Requires Python 3.9+ and archive tools appropriate to the input (`lzop`, `zstd`, `tar`). The core Python service uses only the standard library; optional PDF extraction is listed in `requirements-optional.txt`. Optional integrations and security considerations are documented below.

```bash
python3 -m venv .venv
. .venv/bin/activate
FFDC_HOST=127.0.0.1 FFDC_PORT=8088 python app.py
```

Open `http://127.0.0.1:8088/new-version`. Configure server-side AI/JIRA credentials separately; standalone parsing does not require AI credentials.

Use [config/ffdc-analyzer.env.example](config/ffdc-analyzer.env.example) as the sanitized environment reference and [deploy/ffdc-analyzer.service.example](deploy/ffdc-analyzer.service.example) as the systemd starting point.

## Documentation

- [Environment and Dependencies](docs/Requirements.md)
- [Program Logic and Mermaid Diagrams](docs/LogicPlan.md)
- [Technical Specification and Full Runtime API Reference](docs/Specification.md)
- [Maintenance, Risks and Test Results](docs/Maintenance.md)
- [Source Inventory and Supporting-Script Index](docs/AuditInventory.md)
- [Deployment with a Verified Backup](docs/Deployment.md)

## Codex Handoff

- [Project Handoff](HANDOFF.md)
- [Architecture](ARCHITECTURE.md)
- [Current Status and Next Work](CURRENT_STATUS.md)
- [Import Into Another Codex Account](CODEX_IMPORT.md)

Documentation baseline: local source inspected on 2026-09-30. Consult Maintenance before wider network exposure; current source includes unresolved security and schedule-policy findings.
