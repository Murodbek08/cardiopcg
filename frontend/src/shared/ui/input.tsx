import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { cn } from '@/shared/lib/cn';

const base =
  'w-full rounded-md border border-border bg-surface px-3 text-foreground placeholder:text-muted focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-danger-500';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Larger touch target for the nurse tablet UI. */
  touch?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ className, touch, ...props }, ref) {
  return <input ref={ref} className={cn(base, touch ? 'h-13 text-base' : 'h-10 text-sm', className)} {...props} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...props },
  ref,
) {
  return <textarea ref={ref} className={cn(base, 'min-h-24 py-2 text-sm', className)} {...props} />;
});
