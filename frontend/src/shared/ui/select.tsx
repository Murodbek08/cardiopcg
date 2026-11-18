import { forwardRef, type ReactNode } from 'react';
import { Select as S } from 'radix-ui';
import { IconCheck, IconChevronDown } from '@tabler/icons-react';
import { cn } from '@/shared/lib/cn';

export interface SelectOption {
  value: string;
  label: ReactNode;
}

export interface SelectProps {
  value?: string;
  onValueChange?: (v: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  id?: string;
  className?: string;
  'aria-label'?: string;
  'aria-invalid'?: boolean | 'true' | 'false';
  'aria-describedby'?: string;
  touch?: boolean;
}

/** Radix Select wrapper. Radix forbids empty-string item values; use sentinel `__all__` for "all". */
export const Select = forwardRef<HTMLButtonElement, SelectProps>(function Select(
  { value, onValueChange, options, placeholder, disabled, id, className, touch, ...aria },
  ref,
) {
  return (
    <S.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <S.Trigger
        ref={ref}
        id={id}
        className={cn(
          'inline-flex w-full items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 text-left text-foreground focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-60 data-[placeholder]:text-muted aria-[invalid=true]:border-danger-500',
          touch ? 'h-13 text-base' : 'h-10 text-sm',
          className,
        )}
        {...aria}
      >
        <S.Value placeholder={placeholder} />
        <S.Icon>
          <IconChevronDown size={16} aria-hidden />
        </S.Icon>
      </S.Trigger>
      <S.Portal>
        <S.Content
          position="popper"
          sideOffset={4}
          className="z-[60] max-h-72 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-md border border-border bg-surface shadow-pop"
        >
          <S.Viewport className="p-1">
            {options.map((o) => (
              <S.Item
                key={o.value}
                value={o.value}
                className="relative flex cursor-pointer select-none items-center rounded-sm py-2 pl-8 pr-3 text-sm outline-none data-[highlighted]:bg-surface-2 data-[state=checked]:font-medium"
              >
                <S.ItemIndicator className="absolute left-2">
                  <IconCheck size={14} aria-hidden />
                </S.ItemIndicator>
                <S.ItemText>{o.label}</S.ItemText>
              </S.Item>
            ))}
          </S.Viewport>
        </S.Content>
      </S.Portal>
    </S.Root>
  );
});

export const ALL = '__all__';
