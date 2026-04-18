# Alex x Raenest Enterprise Handover

## Objective

This document provides the operational handover baseline for Raenest to own Alex end-to-end in production.

## Scope of Ownership

1. Product: user journeys, feature flags, and roadmap
2. Engineering: codebase, CI/CD, release quality
3. Platform: AWS infrastructure, reliability, security, cost
4. Operations: monitoring, alerting, incident response

## Production Readiness Additions Implemented

1. Request tracing headers and structured request logs in API middleware
2. Request ID propagation in API error responses
3. Operational readiness endpoint: `GET /api/ops/readiness`
4. Dedicated Raenest integration endpoints with server-to-server API key guard
5. Handover UI page for quick readiness review

## Service Level Objectives (SLO Starter Pack)

1. API availability: 99.9%
2. P95 API latency:
 - core read endpoints <= 400ms
 - analysis trigger endpoints <= 900ms
3. Trade sync success rate (`/api/raenest/sync-trades`): >= 99.5%
4. Analysis completion success rate (queued job): >= 98%
5. Mean time to acknowledge (MTTA): <= 15 minutes

## Key Operational Endpoints

1. Health: `GET /health`
2. Readiness: `GET /api/ops/readiness`
3. Integration intelligence: `GET /api/raenest/portfolio-intelligence/{clerk_user_id}`

## Handover Runbook Index

1. Deployment runbook: `scripts/deploy.py` + terraform guide sequence
2. Recovery runbook: redeploy latest known good image and roll back terraform vars
3. Incident triage:
 - check API health/readiness
 - check CloudWatch logs and request IDs
 - check SQS depth and dead-letter queue
 - check Bedrock availability and region config
4. UI standards runbook: `UI_HANDOVER.md`

## Security Baseline

1. Keep `RAENEST_API_KEY` server-side only
2. Rotate all API keys and secrets on schedule
3. Restrict AWS IAM roles by least privilege
4. Add WAF + IP allowlist for server-to-server endpoints where possible
5. Keep audit logging for critical actions (trade sync and analysis triggers)

## CI/CD Handover Requirements

1. Require branch protection and reviews
2. Run lint, tests, and packaging checks in CI
3. Block deployment on failed checks
4. Attach release notes with migrations/config changes

## Cost Governance

1. Track Aurora, Bedrock, and App Runner daily
2. Add budgets and anomaly alerts
3. Review vector storage growth monthly
4. Auto-clean stale non-prod resources

## Final Acceptance Checklist

1. Raenest engineering can deploy in a clean environment
2. Support can trace incidents with request IDs
3. Ops can determine system readiness via a single endpoint
4. Product can run trade sync -> analysis flow reliably
5. Security can verify key rotation and access controls
