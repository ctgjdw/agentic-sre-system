# Agentic SRE MVP

Multi-agent SRE system that triages alerts, diagnoses incidents, and recommends rectification runbooks to complement a human SRE team. Success metrics: reduced MTTR and Change Failure Rate. Validated via Chaos Engineering simulations.

## Stack
- **Cloud:** AWS
- **Observability / data store:** OpenSearch
- **Chaos:** AWS Fault Injection Service (FIS)
- **Agents:** Claude (Anthropic SDK)
- **Backend / frontend:** to be designed (no existing apps)

## Principles
- **Human-in-the-loop on remediation.** Agents investigate and report; Humans judge the report and follow up accordingly.
- **MVP-first.** Smallest end-to-end slice that proves the value loop: chaos event → alert → agent triage and investigates → output RCA → send for human review and follow-up in slack.
- **Reuse over rebuild.** Prefer managed AWS services and existing observability over custom infra.
- **No production credentials in the repo.** AWS profiles + environment variables only.
- **Always refer to online documentation before planning/implementing** For OpenSRE and AWS services used.

## Status
Bootstrap phase. No code yet. Plan to be drafted before implementation.
