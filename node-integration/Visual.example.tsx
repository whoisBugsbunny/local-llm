// Frontend: render the SAFE "spec" visual with recharts. No AI-written code is executed.
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Spec = { chart_type: string; title?: string; x?: string | null; y?: string[] };

export function SpecChart({ spec, rows }: { spec: Spec; rows: Record<string, any>[] }) {
    const { chart_type, x, y = [] } = spec;
    if (!rows.length) return <p>No data</p>;

    if (chart_type === "line" || chart_type === "bar") {
        const Chart: any = chart_type === "line" ? LineChart : BarChart;
        const Series: any = chart_type === "line" ? Line : Bar;
        return (
            <ResponsiveContainer width="100%" height={320}>
                <Chart data={rows}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey={x ?? undefined} />
                    <YAxis />
                    <Tooltip />
                    {y.map((key) => <Series key={key} dataKey={key} />)}
                </Chart>
            </ResponsiveContainer>
        );
    }
    return <pre>{JSON.stringify(rows.slice(0, 20), null, 2)}</pre>; // fallback: table/kpi/etc.
}

// For AI-written html/js: render ONLY in a sandboxed iframe, e.g.
// <iframe sandbox="allow-scripts" srcDoc={html} onLoad={e => e.currentTarget.contentWindow?.postMessage({ rows }, "*")} />
// (never add allow-same-origin, and never dangerouslySetInnerHTML the generated code).
