import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ColumnDef } from '@tanstack/react-table';
import { StatusBadge } from './status-badge';
import { DataTable } from './data-table';
import { Field } from './field';
import { Input } from './input';
import { EmptyState, Alert } from './feedback';
import { FileDropzone, validateFile } from './file-dropzone';
import { ApiError } from '@/shared/api/errors';
import { RiskBadge, riskZone, RiskGauge } from '@/shared/clinical/risk';
import { AiDisclaimerBadge } from '@/shared/clinical/ai-disclaimer';

interface Row { id: string; name: string }
const columns: ColumnDef<Row>[] = [
  { header: 'Ism', accessorKey: 'name', meta: { sortKey: 'name' } },
  { header: 'ID', accessorKey: 'id' },
];

describe('StatusBadge', () => {
  it('renders a localized text label AND an icon (never colour-only)', () => {
    const { container } = render(<StatusBadge kind="exam" value="ai_ready" />);
    expect(screen.getByText('Shifokor kutilmoqda')).toBeInTheDocument();
    expect(container.querySelector('svg')).not.toBeNull();
  });
  it('covers severity and interaction levels', () => {
    render(<><StatusBadge kind="severity" value="critical" /><StatusBadge kind="interaction" value="contraindicated" /></>);
    expect(screen.getByText('Kritik')).toBeInTheDocument();
    expect(screen.getByText("Qarshi ko'rsatma")).toBeInTheDocument();
  });
  it('renders a dash for empty values', () => {
    render(<StatusBadge kind="exam" value={null} />);
    expect(screen.getByText('-')).toBeInTheDocument();
  });
});

describe('DataTable', () => {
  it('renders rows, toggles server sort and paginates (offset mode)', async () => {
    const onSort = vi.fn();
    const onPage = vi.fn();
    render(
      <DataTable
        columns={columns}
        data={[{ id: 'a', name: 'Alpha' }, { id: 'b', name: 'Beta' }]}
        sort="name"
        onSortChange={onSort}
        pagination={{ mode: 'offset', page: 1, pageSize: 20, total: 45, onPageChange: onPage }}
      />,
    );
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Ism/ })).toHaveAttribute('aria-sort', 'ascending');
    await userEvent.click(within(screen.getByRole('columnheader', { name: /Ism/ })).getByRole('button'));
    expect(onSort).toHaveBeenCalledWith('-name');
    await userEvent.click(screen.getByRole('button', { name: 'Keyingi' }));
    expect(onPage).toHaveBeenCalledWith(2);
    expect(screen.getByRole('button', { name: 'Oldingi' })).toBeDisabled();
  });
  it('shows an empty state when there are no rows', () => {
    render(<DataTable columns={columns} data={[]} emptyState={<EmptyState title="Bo'sh" />} />);
    expect(screen.getByText("Bo'sh")).toBeInTheDocument();
  });
  it('shows an error state with retry (and the request id) when the query failed', async () => {
    const retry = vi.fn();
    const err = new ApiError({ status: 500, code: 'INTERNAL_ERROR', message: 'x', requestId: 'req-1234567890abc' });
    render(<DataTable columns={columns} data={[]} error={err} onRetry={retry} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Server xatosi');
    expect(screen.getByText(/req-12345678/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Qayta urinish/ }));
    expect(retry).toHaveBeenCalled();
  });
  it('fires onRowClick', async () => {
    const click = vi.fn();
    render(<DataTable columns={columns} data={[{ id: 'a', name: 'Alpha' }]} onRowClick={click} />);
    await userEvent.click(screen.getByText('Alpha'));
    expect(click).toHaveBeenCalledWith({ id: 'a', name: 'Alpha' });
  });
});

describe('Field accessibility wiring', () => {
  it('links label, error and aria-invalid', () => {
    render(<Field label="Parol" error="Majburiy maydon" required><Input /></Field>);
    const input = screen.getByLabelText(/Parol/);
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAttribute('aria-required', 'true');
    expect(input.getAttribute('aria-describedby')).toBeTruthy();
    expect(screen.getByRole('alert')).toHaveTextContent('Majburiy maydon');
  });
});

describe('FileDropzone validation', () => {
  const f = (name: string, size = 10) => new File([new Uint8Array(size)], name);
  it('rejects wrong extension and oversize files', () => {
    expect(validateFile(f('a.exe'), ['.wav', '.mp3'], 100)).toBe('type');
    expect(validateFile(f('a.wav', 500), ['.wav'], 100)).toBe('size');
    expect(validateFile(f('A.WAV', 50), ['.wav'], 100)).toBeNull();
  });
  it('reports rejections and accepted files', async () => {
    const onFiles = vi.fn();
    const onReject = vi.fn();
    const { container } = render(<FileDropzone multiple accept={['.wav']} maxSizeBytes={100} onFiles={onFiles} onReject={onReject} />);
    const input = container.querySelector('input[type=file]') as HTMLInputElement;
    await userEvent.upload(input, [f('ok.wav'), new File([new Uint8Array(500)], 'big.wav')], { applyAccept: false });
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledWith([expect.objectContaining({ reason: 'size' })]);
  });
});

describe('clinical components', () => {
  it('maps scores to the four risk zones with configurable thresholds', () => {
    expect(riskZone(10)).toBe('low');
    expect(riskZone(30)).toBe('moderate');
    expect(riskZone(60)).toBe('high');
    expect(riskZone(90)).toBe('critical');
    expect(riskZone(50, { moderate: 20, high: 40, critical: 60 })).toBe('high');
  });
  it('RiskBadge/RiskGauge print the zone name as text', () => {
    render(<><RiskBadge score={90} /><RiskGauge value={58} /></>);
    expect(screen.getByText('Kritik')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /58/ })).toBeInTheDocument();
    expect(screen.getAllByText("O'rta").length).toBeGreaterThan(0);
  });
  it('AI disclaimer carries the mandatory wording', () => {
    render(<AiDisclaimerBadge />);
    expect(screen.getByText(/shifokor tasdiqlaydi/)).toBeInTheDocument();
  });
  it('Alert uses an assertive role for warnings', () => {
    render(<Alert tone="warning" title="Diqqat">x</Alert>);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });
});
