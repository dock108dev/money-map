import type { PathResult } from "./life-lab-types";

function currency(value: string) {
  return Number(value).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export function ProjectionTable({ path }: { path: PathResult }) {
  const annual = path.periods.filter((_, index) => index % 12 === 0 || index === path.periods.length - 1);
  return (
    <div className="table-scroll">
      <table className="life-projection-table">
        <thead><tr><th>Age</th><th>Cash</th><th>Accessible</th><th>Retirement</th><th>Total spendable</th><th>State</th></tr></thead>
        <tbody>
          {annual.map((row) => (
            <tr key={row.month}>
              <td>{Math.floor(row.age_months / 12)}</td>
              <td>{currency(row.cash)}</td>
              <td>{currency(row.accessible_investments)}</td>
              <td>{currency(row.pretax_retirement)}</td>
              <td>{currency(row.total_spendable)}</td>
              <td>{row.working ? "Working" : "Work optional"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
