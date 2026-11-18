import {
  Area, AreaChart, Bar, BarChart as RBarChart, CartesianGrid, Cell, Legend, Line, LineChart as RLineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceArea,
} from 'recharts';
import { useChartTheme } from './theme';
import { formatNumber } from '@/shared/lib/format';

export interface SeriesDef {
  key: string;
  label: string;
  color?: string;
}

const MAX_POINTS = 500;

/** Cheap uniform downsample (backend should already LTTB-downsample; this is a safety net). */
export function capPoints<T>(data: T[], max = MAX_POINTS): T[] {
  if (data.length <= max) return data;
  const step = Math.ceil(data.length / max);
  return data.filter((_, i) => i % step === 0);
}

export function TimeSeriesChart({ data, series, xKey = 't', area = false, unit, zones }: {
  data: Record<string, string | number | null>[];
  series: SeriesDef[];
  xKey?: string;
  area?: boolean;
  unit?: string;
  zones?: { from: number; to: number; color: string }[];
}) {
  const th = useChartTheme();
  const rows = capPoints(data);
  const Chart = area ? AreaChart : RLineChart;
  return (
    <ResponsiveContainer width="100%" height="100%" debounce={150}>
      <Chart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
        <CartesianGrid stroke={th.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey={xKey} tick={{ fill: th.axis, fontSize: 12 }} tickLine={false} axisLine={{ stroke: th.grid }} minTickGap={24} />
        <YAxis tick={{ fill: th.axis, fontSize: 12 }} tickLine={false} axisLine={false} width={44} allowDecimals={false} unit={unit} />
        {zones?.map((z, i) => (
          <ReferenceArea key={i} y1={z.from} y2={z.to} fill={z.color} fillOpacity={0.12} />
        ))}
        <Tooltip
          formatter={(v) => (typeof v === 'number' ? formatNumber(v, v % 1 ? 1 : 0) : String(v))}
          contentStyle={{ background: th.surface, border: `1px solid ${th.grid}`, borderRadius: 8, color: th.text }}
          labelStyle={{ color: th.text }}
        />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {series.map((s, i) => {
          const color = s.color ?? th.series[i % th.series.length]!;
          return area ? (
            <Area key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={color} fill={color} fillOpacity={0.15} strokeWidth={2} connectNulls={false} isAnimationActive={rows.length < 200} />
          ) : (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={color} strokeWidth={2} dot={rows.length < 40} connectNulls={false} isAnimationActive={rows.length < 200} />
          );
        })}
      </Chart>
    </ResponsiveContainer>
  );
}

export function DonutChart({ data, centerLabel, centerValue }: {
  data: { name: string; value: number; color?: string }[];
  centerLabel?: string;
  centerValue?: string;
}) {
  const th = useChartTheme();
  const total = data.reduce((a, d) => a + d.value, 0);
  return (
    <div className="flex h-full flex-col items-center gap-3 sm:flex-row">
      <div className="relative h-full min-h-40 w-full flex-1">
        <ResponsiveContainer width="100%" height="100%" debounce={150}>
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="58%" outerRadius="88%" paddingAngle={2} stroke={th.surface} strokeWidth={2}>
              {data.map((d, i) => (
                <Cell key={d.name} fill={d.color ?? th.series[i % th.series.length]} />
              ))}
            </Pie>
            <Tooltip
              formatter={(v, n) => [`${formatNumber(Number(v))} (${total ? Math.round((Number(v) / total) * 100) : 0}%)`, n]}
              contentStyle={{ background: th.surface, border: `1px solid ${th.grid}`, borderRadius: 8, color: th.text }}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-h2 font-bold">{centerValue ?? formatNumber(total)}</span>
          {centerLabel && <span className="text-xs text-muted">{centerLabel}</span>}
        </div>
      </div>
      {/* Legend as a list/table: accessible and does not rely on colour only */}
      <ul className="w-full shrink-0 space-y-1 text-sm sm:w-44">
        {data.map((d, i) => (
          <li key={d.name} className="flex items-center justify-between gap-2">
            <span className="flex min-w-0 items-center gap-2">
              <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: d.color ?? th.series[i % th.series.length] }} />
              <span className="truncate">{d.name}</span>
            </span>
            <span className="tabular-nums text-muted">{formatNumber(d.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function BarsChart({ data, series, xKey = 'name', horizontal = false, stacked = false, unit }: {
  data: Record<string, string | number | null>[];
  series: SeriesDef[];
  xKey?: string;
  horizontal?: boolean;
  stacked?: boolean;
  unit?: string;
}) {
  const th = useChartTheme();
  return (
    <ResponsiveContainer width="100%" height="100%" debounce={150}>
      <RBarChart data={capPoints(data)} layout={horizontal ? 'vertical' : 'horizontal'} margin={{ top: 8, right: 12, bottom: 0, left: horizontal ? 8 : -8 }}>
        <CartesianGrid stroke={th.grid} strokeDasharray="3 3" horizontal={!horizontal} vertical={horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" tick={{ fill: th.axis, fontSize: 12 }} tickLine={false} axisLine={false} unit={unit} allowDecimals={false} />
            <YAxis type="category" dataKey={xKey} tick={{ fill: th.axis, fontSize: 12 }} tickLine={false} axisLine={false} width={110} />
          </>
        ) : (
          <>
            <XAxis dataKey={xKey} tick={{ fill: th.axis, fontSize: 12 }} tickLine={false} axisLine={{ stroke: th.grid }} />
            <YAxis tick={{ fill: th.axis, fontSize: 12 }} tickLine={false} axisLine={false} width={40} unit={unit} allowDecimals={false} />
          </>
        )}
        <Tooltip
          cursor={{ fill: th.grid, fillOpacity: 0.4 }}
          formatter={(v) => (typeof v === 'number' ? formatNumber(v, v % 1 ? 1 : 0) : String(v))}
          contentStyle={{ background: th.surface, border: `1px solid ${th.grid}`, borderRadius: 8, color: th.text }}
        />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {series.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color ?? th.series[i % th.series.length]} radius={[3, 3, 0, 0]} stackId={stacked ? 'a' : undefined} maxBarSize={36} isAnimationActive={data.length < 100} />
        ))}
      </RBarChart>
    </ResponsiveContainer>
  );
}

/** Minimal frame-less trend line for KPI cards. */
export function Sparkline({ values, label }: { values: number[]; label: string }) {
  const th = useChartTheme();
  const data = values.map((v, i) => ({ i, v }));
  return (
    <div role="img" aria-label={label} className="h-full w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <Area type="monotone" dataKey="v" stroke={th.brand} fill={th.brand} fillOpacity={0.12} strokeWidth={1.5} isAnimationActive={false} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
