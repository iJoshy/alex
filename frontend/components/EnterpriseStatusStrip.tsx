interface EnterpriseStatusStripProps {
  lastAnalysisDate?: string | null;
  integrationName?: string;
  environment?: string;
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "Not available";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Not available";
  return parsed.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function EnterpriseStatusStrip({
  lastAnalysisDate,
  integrationName = "Raenest US Shares",
  environment = process.env.NODE_ENV === "production" ? "Production" : "Development",
}: EnterpriseStatusStripProps) {
  return (
    <div className="surface-card-muted p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Integration Context</p>
          <p className="text-sm font-semibold text-dark">{integrationName}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="status-chip status-chip-success">
            <span className="h-2 w-2 rounded-full bg-success" />
            API Healthy
          </span>
          <span className="status-chip status-chip-info">{environment}</span>
          <span className="status-chip status-chip-warning">
            Last AI analysis: {formatTimestamp(lastAnalysisDate)}
          </span>
        </div>
      </div>
    </div>
  );
}

