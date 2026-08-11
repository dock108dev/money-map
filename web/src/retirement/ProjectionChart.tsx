import type { PathResult } from "../life-lab/life-lab-types";

const colors: Record<string, string> = {
  middle: "#27785d",
  rough: "#d18a35",
  early_crash: "#b64c58",
};

function annualPoints(path: PathResult) {
  return path.periods.filter((_, index) => index % 12 === 0 || index === path.periods.length - 1);
}

export function ProjectionChart({ paths }: { paths: PathResult[] }) {
  const series = paths.map((path) => ({ path, points: annualPoints(path) }));
  const values = series.flatMap(({ points }) => points.map((row) => Number(row.total_spendable)));
  const max = Math.max(...values, 1);
  const width = 760;
  const height = 270;
  const inset = 24;
  const count = Math.max(...series.map(({ points }) => points.length), 2);
  const point = (value: number, index: number) => {
    const x = inset + (index / (count - 1)) * (width - inset * 2);
    const y = height - inset - (Math.max(0, value) / max) * (height - inset * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  };

  return (
    <div className="retirement-chart-wrap">
      <svg className="retirement-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Projected spendable assets under three deterministic paths">
        <line x1={inset} y1={height - inset} x2={width - inset} y2={height - inset} className="chart-axis" />
        {series.map(({ path, points }) => (
          <polyline
            key={path.path_key}
            points={points.map((row, index) => point(Number(row.total_spendable), index)).join(" ")}
            fill="none"
            stroke={colors[path.path_key]}
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
      </svg>
      <div className="retirement-chart-legend">
        {paths.map((path) => <span key={path.path_key}><i style={{ background: colors[path.path_key] }} />{path.path_label}</span>)}
      </div>
    </div>
  );
}
