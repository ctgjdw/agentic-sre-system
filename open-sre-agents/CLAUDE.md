# OpenSRE MVP

OpenSRE (link: https://www.opensre.com/docs) demo that utilises agents to triage alerts, diagnose incidents, and produce a root cause analysis (RCA) report to complement a human SRE team and reduce MTTR. Validated via Chaos Engineering simulations.

## Stack

- **Cloud:** AWS Free Tier
- **Frontend/Backend:** ECS EC2, demo apps to be created
- **Data layer:** AWS RDS
- **Chaos:** AWS Fault Injection Service (FIS)
- **Agents:** OpenSRE platform using Claude models
- **Observability:** AWS Cloudwatch

## Principles

- **MVP-first.** Smallest end-to-end slice that proves the value loop: chaos event → alert → agent triage and investigates → output RCA → send for human review and follow-up in slack
- **No production credentials in the repo.** AWS profiles + environment variables only.
- **Always refer to online documentation using find-docs skill or fetch** before you do any action to make sure that you have the latest information

## Status

Bootstrap phase. No code yet. Plan to be drafted before implementation.
