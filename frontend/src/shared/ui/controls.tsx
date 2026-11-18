import { forwardRef, type ComponentPropsWithoutRef, type ReactNode } from 'react';
import { Checkbox as C, Switch as Sw, RadioGroup as R } from 'radix-ui';
import { IconCheck } from '@tabler/icons-react';
import { cn } from '@/shared/lib/cn';

export const Checkbox = forwardRef<HTMLButtonElement, ComponentPropsWithoutRef<typeof C.Root>>(function Checkbox(
  { className, ...props },
  ref,
) {
  return (
    <C.Root
      ref={ref}
      className={cn(
        'flex h-5 w-5 shrink-0 items-center justify-center rounded border border-border bg-surface data-[state=checked]:border-brand-600 data-[state=checked]:bg-brand-600 focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50',
        className,
      )}
      {...props}
    >
      <C.Indicator className="text-white">
        <IconCheck size={14} stroke={3} aria-hidden />
      </C.Indicator>
    </C.Root>
  );
});

export const Switch = forwardRef<HTMLButtonElement, ComponentPropsWithoutRef<typeof Sw.Root>>(function Switch(
  { className, ...props },
  ref,
) {
  return (
    <Sw.Root
      ref={ref}
      className={cn(
        'relative h-6 w-11 shrink-0 rounded-full bg-border transition-colors data-[state=checked]:bg-brand-600 focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50',
        className,
      )}
      {...props}
    >
      <Sw.Thumb className="block h-5 w-5 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[22px]" />
    </Sw.Root>
  );
});

export function CheckboxField({ label, className, ...props }: ComponentPropsWithoutRef<typeof C.Root> & { label: ReactNode }) {
  return (
    <label className={cn('flex cursor-pointer items-center gap-2 text-sm', className)}>
      <Checkbox {...props} />
      <span>{label}</span>
    </label>
  );
}

export function RadioGroup({ className, ...props }: ComponentPropsWithoutRef<typeof R.Root>) {
  return <R.Root className={cn('flex flex-wrap gap-3', className)} {...props} />;
}

export function RadioItem({ value, label }: { value: string; label: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm">
      <R.Item
        value={value}
        className="flex h-5 w-5 items-center justify-center rounded-full border border-border bg-surface data-[state=checked]:border-brand-600 focus-visible:outline-2 focus-visible:outline-ring"
      >
        <R.Indicator className="h-2.5 w-2.5 rounded-full bg-brand-600" />
      </R.Item>
      {label}
    </label>
  );
}
