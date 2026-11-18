import { useEffect, useRef } from 'react';
import type { ECharts } from 'echarts/core';
import { useChartTheme } from './theme';

export interface HeatCell {
  x: number; // hour 0-23
  y: number; // weekday index 0-6 (Mon..Sun)
  value: number;
}

/**
 * ECharts heatmap (weekday x hour). ECharts is imported dynamically and only the needed modules are
 * registered, so it never lands in the initial bundle. Single-hue sequential scale (brand-100 -> brand-700).
 */
export function Heatmap({ cells, xLabels, yLabels, valueLabel }: { cells: HeatCell[]; xLabels: string[]; yLabels: string[]; valueLabel: string }) {
  const el = useRef<HTMLDivElement>(null);
  const th = useChartTheme();

  useEffect(() => {
    let disposed = false;
    let chart: ECharts | null = null;
    let ro: ResizeObserver | null = null;
    void (async () => {
      const [core, charts, components, renderers] = await Promise.all([
        import('echarts/core'),
        import('echarts/charts'),
        import('echarts/components'),
        import('echarts/renderers'),
      ]);
      if (disposed || !el.current) return;
      core.use([charts.HeatmapChart, components.GridComponent, components.TooltipComponent, components.VisualMapComponent, renderers.CanvasRenderer]);
      chart = core.init(el.current);
      const max = Math.max(1, ...cells.map((c) => c.value));
      chart.setOption({
        animation: cells.length < 200,
        grid: { left: 40, right: 12, top: 8, bottom: 52 },
        tooltip: { position: 'top', formatter: (p: { value: number[] }) => `${yLabels[p.value[1]!]} ${xLabels[p.value[0]!]}: <b>${p.value[2]}</b> ${valueLabel}`, backgroundColor: th.surface, borderColor: th.grid, textStyle: { color: th.text } },
        xAxis: { type: 'category', data: xLabels, splitArea: { show: false }, axisLabel: { color: th.axis, interval: 2 }, axisLine: { lineStyle: { color: th.grid } } },
        yAxis: { type: 'category', data: yLabels, inverse: true, axisLabel: { color: th.axis }, axisLine: { lineStyle: { color: th.grid } } },
        visualMap: { min: 0, max, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 120, textStyle: { color: th.axis }, inRange: { color: [th.scale[0], th.scale[3]] } },
        series: [{ type: 'heatmap', data: cells.map((c) => [c.x, c.y, c.value]), itemStyle: { borderColor: th.surface, borderWidth: 1, borderRadius: 2 }, emphasis: { itemStyle: { borderColor: th.text, borderWidth: 1 } } }],
      });
      ro = new ResizeObserver(() => chart?.resize());
      ro.observe(el.current);
    })();
    return () => {
      disposed = true;
      ro?.disconnect();
      chart?.dispose();
    };
  }, [cells, xLabels, yLabels, valueLabel, th]);

  return <div ref={el} role="img" aria-label={valueLabel} className="h-full w-full" />;
}
