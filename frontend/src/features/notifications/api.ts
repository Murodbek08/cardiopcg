import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, post, qk } from '@/shared';
import type { NotificationItem, Paged } from '@/shared/api/types';

export interface NotificationFilter {
  is_read?: boolean;
  type?: string;
  limit?: number;
  cursor?: string;
}

export const notificationsApi = {
  list: (f: NotificationFilter) => get<Paged<NotificationItem>>('/notifications', { ...f }),
  unread: () => get<{ count: number }>('/notifications/unread-count'),
  read: (id: string) => post(`/notifications/${id}/read`),
  readAll: () => post('/notifications/read-all'),
};

export function useNotifications(f: NotificationFilter, enabled = true) {
  return useQuery({ queryKey: qk.notifications.list(f), queryFn: () => notificationsApi.list(f), enabled, refetchInterval: 30_000 });
}

export function useUnreadCount() {
  return useQuery({ queryKey: qk.notifications.unread, queryFn: notificationsApi.unread, refetchInterval: 60_000, select: (d) => d.count });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: notificationsApi.read,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['notifications'] }),
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: notificationsApi.readAll,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['notifications'] }),
  });
}

export function notificationTarget(n: NotificationItem): string | null {
  const id = n.payload?.examination_id;
  return typeof id === 'string' ? `/exams/${id}` : null;
}
