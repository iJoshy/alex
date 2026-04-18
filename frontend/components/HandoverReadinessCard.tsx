interface HandoverReadinessCardProps {
  title: string;
  items: string[];
  variant?: "info" | "success" | "warning";
}

export default function HandoverReadinessCard({
  title,
  items,
  variant = "info",
}: HandoverReadinessCardProps) {
  const variantClass =
    variant === "success"
      ? "status-chip-success"
      : variant === "warning"
      ? "status-chip-warning"
      : "status-chip-info";

  return (
    <div className="surface-card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-base font-semibold text-dark">{title}</h3>
        <span className={`status-chip ${variantClass}`}>{items.length} checks</span>
      </div>
      <ul className="space-y-2 text-sm text-gray-700">
        {items.map((item) => (
          <li key={item} className="flex items-start gap-2">
            <span className="mt-1 h-2 w-2 rounded-full bg-primary" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

