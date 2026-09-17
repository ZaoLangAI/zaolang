'use client';

import { Panel, PanelGroup, PanelResizeHandle, type PanelGroupProps } from 'react-resizable-panels';

import { cn } from '@/lib/cn';

export const ResizablePanelGroup = ({ className, ...props }: PanelGroupProps) => (
  <PanelGroup className={cn('flex size-full', className)} {...props} />
);

export const ResizablePanel = Panel;

export function ResizableHandle({ className }: { className?: string }) {
  return (
    <PanelResizeHandle
      className={cn(
        'group relative shrink-0 bg-border data-[panel-group-direction=vertical]:h-px data-[panel-group-direction=horizontal]:w-px',
        'after:absolute after:inset-0 data-[panel-group-direction=vertical]:after:-inset-y-1 data-[panel-group-direction=horizontal]:after:-inset-x-1',
        'hover:bg-primary data-[resize-handle-active]:bg-primary',
        className,
      )}
    />
  );
}
