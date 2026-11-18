import type { ComponentPropsWithoutRef } from 'react';
import { Tabs as T, Tooltip as Tt, DropdownMenu as DM } from 'radix-ui';
import type { ReactNode } from 'react';
import { cn } from '@/shared/lib/cn';

export const Tabs = T.Root;

export function TabsList({ className, ...props }: ComponentPropsWithoutRef<typeof T.List>) {
  return <T.List className={cn('flex gap-1 overflow-x-auto border-b border-border', className)} {...props} />;
}
export function TabsTrigger({ className, ...props }: ComponentPropsWithoutRef<typeof T.Trigger>) {
  return (
    <T.Trigger
      className={cn(
        '-mb-px whitespace-nowrap border-b-2 border-transparent px-4 py-2.5 text-sm font-medium text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring data-[state=active]:border-brand-600 data-[state=active]:text-foreground',
        className,
      )}
      {...props}
    />
  );
}
export function TabsContent({ className, ...props }: ComponentPropsWithoutRef<typeof T.Content>) {
  return <T.Content className={cn('pt-4 focus-visible:outline-none', className)} {...props} />;
}

export const TooltipProvider = Tt.Provider;
export function Tooltip({ content, children, side = 'top' }: { content: ReactNode; children: ReactNode; side?: 'top' | 'bottom' | 'left' | 'right' }) {
  return (
    <Tt.Root delayDuration={200}>
      <Tt.Trigger asChild>{children}</Tt.Trigger>
      <Tt.Portal>
        <Tt.Content side={side} sideOffset={6} className="z-[70] max-w-xs rounded-md bg-foreground px-2.5 py-1.5 text-xs text-background shadow-pop">
          {content}
        </Tt.Content>
      </Tt.Portal>
    </Tt.Root>
  );
}

export const DropdownMenu = DM.Root;
export const DropdownMenuTrigger = DM.Trigger;
export function DropdownMenuContent({ className, align = 'end', ...props }: ComponentPropsWithoutRef<typeof DM.Content>) {
  return (
    <DM.Portal>
      <DM.Content
        align={align}
        sideOffset={6}
        className={cn('z-[60] min-w-48 rounded-md border border-border bg-surface p-1 shadow-pop', className)}
        {...props}
      />
    </DM.Portal>
  );
}
export function DropdownMenuItem({ className, danger, ...props }: ComponentPropsWithoutRef<typeof DM.Item> & { danger?: boolean }) {
  return (
    <DM.Item
      className={cn(
        'flex cursor-pointer select-none items-center gap-2 rounded-sm px-3 py-2 text-sm outline-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[highlighted]:bg-surface-2',
        danger && 'text-danger-500',
        className,
      )}
      {...props}
    />
  );
}
export const DropdownMenuSeparator = (props: ComponentPropsWithoutRef<typeof DM.Separator>) => (
  <DM.Separator className="my-1 h-px bg-border" {...props} />
);
export const DropdownMenuLabel = (props: ComponentPropsWithoutRef<typeof DM.Label>) => (
  <DM.Label className="px-3 py-1.5 text-xs font-medium text-muted" {...props} />
);
