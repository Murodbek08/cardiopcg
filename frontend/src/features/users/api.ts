import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { del, get, patch, post, qk, normalizePage } from '@/shared';
import type { Paged, ResetPasswordResult, UserCreateInput, UserListItem, UserUpdateInput } from '@/shared/api/types';

export interface UsersFilter {
  role?: string;
  status?: string;
  q?: string;
  sort?: string;
  page: number;
  page_size: number;
}

export function useUsers(f: UsersFilter) {
  return useQuery({
    queryKey: qk.users.list(f),
    queryFn: async ({ signal }) => normalizePage(await get<Paged<UserListItem> | UserListItem[]>('/users', { ...f }, signal)),
    placeholderData: keepPreviousData,
  });
}

export function useUser(id: string) {
  return useQuery({ queryKey: qk.users.detail(id), queryFn: ({ signal }) => get<UserListItem>(`/users/${id}`, undefined, signal) });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: UserCreateInput) => post<UserListItem>('/users', body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.users.all }),
  });
}

export function useUpdateUser(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: UserUpdateInput) => patch<UserListItem>(`/users/${id}`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.users.all }),
  });
}

export type UserAction = 'suspend' | 'activate' | 'unlock' | 'reset-password';

export function useUserAction(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (action: UserAction) => post<ResetPasswordResult | undefined>(`/users/${id}/${action}`, action === 'reset-password' ? { mode: 'temp_password' } : undefined),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.users.all }),
  });
}

export function useDeleteUser(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => del(`/users/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.users.all }),
  });
}
