import Head from "next/head";
import Layout from "../components/Layout";
import HandoverReadinessCard from "../components/HandoverReadinessCard";

const engineeringChecks = [
  "CI pipeline for lint, tests, and security scanning is active",
  "Environment variables are documented and rotated",
  "API contracts for /api/raenest/* are versioned",
  "Rollback path is documented for each deployment stage",
];

const operationsChecks = [
  "CloudWatch dashboards and alarms are linked to on-call routing",
  "Runbooks cover SQS backlog, API latency, and Bedrock failures",
  "RTO/RPO targets are documented for critical services",
  "Cost alerts and anomaly detection are enabled",
];

const productChecks = [
  "US shares intelligence widgets reviewed for production UX",
  "Risk language and disclaimers approved by compliance",
  "In-app event taxonomy finalized for analytics",
  "Support playbook for user-facing incidents is published",
];

export default function HandoverPage() {
  return (
    <>
      <Head>
        <title>Handover - Alex x Raenest</title>
      </Head>
      <Layout>
        <div className="min-h-screen bg-gray-50 py-8">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="enterprise-hero p-6 mb-8">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                Enterprise Transition
              </p>
              <h1 className="text-3xl font-bold text-dark mb-2">Raenest Ownership Handover</h1>
              <p className="text-sm text-gray-600">
                This control center summarizes what is required for a clean transfer from build team
                to Raenest engineering, operations, and product.
              </p>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
              <HandoverReadinessCard
                title="Engineering Readiness"
                items={engineeringChecks}
                variant="info"
              />
              <HandoverReadinessCard
                title="Operations Readiness"
                items={operationsChecks}
                variant="warning"
              />
              <HandoverReadinessCard
                title="Product Readiness"
                items={productChecks}
                variant="success"
              />
            </div>

            <div className="surface-card p-6">
              <h2 className="text-xl font-semibold text-dark mb-4">Handover Artifacts</h2>
              <ul className="space-y-3 text-sm text-gray-700">
                <li>
                  <code className="rounded bg-gray-100 px-2 py-1">/RAENEST_INTEGRATION.md</code>
                  {" "}Integration contract and implementation details
                </li>
                <li>
                  <code className="rounded bg-gray-100 px-2 py-1">/ENTERPRISE_HANDOVER.md</code>
                  {" "}Ownership model, SLOs, security posture, and runbook index
                </li>
                <li>
                  <code className="rounded bg-gray-100 px-2 py-1">/UI_HANDOVER.md</code>
                  {" "}Design tokens, UX standards, and production UI guidelines
                </li>
              </ul>
            </div>
          </div>
        </div>
      </Layout>
    </>
  );
}

