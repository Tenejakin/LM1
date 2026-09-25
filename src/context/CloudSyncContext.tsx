import AsyncStorage from '@react-native-async-storage/async-storage';
import React, { createContext, PropsWithChildren, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { AppState, Platform } from 'react-native';
import type { Session } from '@supabase/supabase-js';

import { supabase, supabaseConfigured } from '@/services/supabase';
import type { CaptureFramePreview, Putt, Shot } from '@/types';

type CloudSyncValue = {
  configured: boolean;
  session: Session | null;
  authReady: boolean;
  busy: boolean;
  error: string | null;
  notice: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  resetPassword: (email: string) => Promise<void>;
  syncShots: (shots: Shot[]) => Promise<void>;
  syncPutts: (putts: Putt[]) => Promise<void>;
  uploadShotCapture: (shot: Shot, primaryBase64: string, secondaryBase64?: string) => Promise<void>;
  repairShotImage: (shotId: string) => Promise<{ imagePath: string | null; secondaryImagePath: string | null }>;
  getShotImage: (shotId: string, camera?: 'primary' | 'secondary') => Promise<string>;
  beginFrameUpload: (shotId: string) => Promise<{ token: string; frameCount: number; expiresAt: string }>;
  getUploadedFrameIndices: (shotId: string) => Promise<number[]>;
  getCloudShotFrame: (shotId: string, frameIndex: number) => Promise<CaptureFramePreview>;
  restoreShots: () => Promise<Shot[]>;
  restorePutts: () => Promise<Putt[]>;
  savePreference: (key: string, value: string) => Promise<void>;
  restorePreferences: () => Promise<Record<string, string>>;
};

const CloudSyncContext = createContext<CloudSyncValue | null>(null);
const PENDING_SHOTS_KEY = '@pinpoint/cloud-pending-shots';
const PENDING_PUTTS_KEY = '@pinpoint/cloud-pending-putts';
const PENDING_IMAGES_KEY = '@pinpoint/cloud-pending-images';

type PendingImage = { shot: Shot; primaryBase64: string; secondaryBase64?: string };

async function readQueue<T>(key: string): Promise<T[]> {
  try {
    const raw = await AsyncStorage.getItem(key);
    return raw ? JSON.parse(raw) as T[] : [];
  } catch {
    return [];
  }
}

async function functionErrorMessage(error: Error): Promise<string> {
  const response = (error as Error & { context?: Response }).context;
  if (response && typeof response.json === 'function') {
    try {
      const body = await response.json() as { error?: string };
      if (body.error) return body.error;
    } catch { /* Keep the transport error when the response is not JSON. */ }
  }
  return error.message;
}

export function CloudSyncProvider({ children }: PropsWithChildren) {
  const [session, setSession] = useState<Session | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const imageWork = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    if (!supabase) { setAuthReady(true); return; }
    const client = supabase;
    void client.auth.getSession().then(({ data, error: authError }) => {
      if (authError) setError(authError.message);
      setSession(data.session);
      setAuthReady(true);
    }).catch((caught: unknown) => {
      setError(caught instanceof Error ? caught.message : 'Could not restore the sign-in session.');
      setAuthReady(true);
    });
    const { data } = client.auth.onAuthStateChange((_event, nextSession) => setSession(nextSession));
    const appStateSubscription = Platform.OS === 'web' ? null : AppState.addEventListener('change', (state) => {
      if (state === 'active') void client.auth.startAutoRefresh();
      else void client.auth.stopAutoRefresh();
    });
    if (Platform.OS !== 'web' && AppState.currentState === 'active') void client.auth.startAutoRefresh();
    return () => {
      data.subscription.unsubscribe();
      appStateSubscription?.remove();
      if (Platform.OS !== 'web') void client.auth.stopAutoRefresh();
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    if (!supabase) throw new Error('Cloud sync is not configured. Add the Supabase environment variables.');
    setBusy(true); setError(null); setNotice(null);
    try {
      const { error: authError } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
      if (authError) throw authError;
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'Could not sign in.';
      setError(message); throw caught;
    } finally { setBusy(false); }
  }, []);

  const signUp = useCallback(async (email: string, password: string) => {
    if (!supabase) throw new Error('Cloud sync is not configured. Add the Supabase environment variables.');
    setBusy(true); setError(null); setNotice(null);
    try {
      const { data, error: authError } = await supabase.auth.signUp({ email: email.trim(), password });
      if (authError) throw authError;
      setNotice(data.session
        ? 'Your account is ready and you are signed in.'
        : 'Account created. Check your email for a confirmation link, then return here to sign in.');
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'Could not create an account.';
      setError(message); throw caught;
    } finally { setBusy(false); }
  }, []);

  const resetPassword = useCallback(async (email: string) => {
    if (!supabase) throw new Error('Cloud sync is not configured. Add the Supabase environment variables.');
    setBusy(true); setError(null); setNotice(null);
    try {
      const { error: authError } = await supabase.auth.resetPasswordForEmail(email.trim());
      if (authError) throw authError;
      setNotice('If an account exists for that email, Supabase will send password reset instructions.');
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'Could not request a password reset.';
      setError(message); throw caught;
    } finally { setBusy(false); }
  }, []);

  const signOut = useCallback(async () => {
    if (!supabase) return;
    const { error: authError } = await supabase.auth.signOut();
    if (authError) throw authError;
  }, []);

  const syncRows = useCallback(async <T extends { id: string }>(table: 'shots' | 'putts', queueKey: string, rows: T[]) => {
    if (!session?.user || !supabase) return;
    const scopedQueueKey = `${queueKey}:${session.user.id}`;
    const pending = await readQueue<T>(scopedQueueKey);
    const allRows = new Map([...pending, ...rows].map((item) => [item.id, item]));
    const payload = [...allRows.values()].map((item) => ({ user_id: session.user.id, id: item.id, data: item }));
    if (!payload.length) return;
    const { error: dbError } = table === 'shots'
      ? await supabase.rpc('sync_shots', { p_shots: [...allRows.values()] })
      : await supabase.from('putts').upsert(payload, { onConflict: 'user_id,id' });
    if (dbError) {
      setError(`Cloud sync failed: ${dbError.message}`);
      await AsyncStorage.setItem(scopedQueueKey, JSON.stringify([...allRows.values()]));
      throw dbError;
    }
    await AsyncStorage.removeItem(scopedQueueKey);
  }, [session]);

  const syncShots = useCallback((rows: Shot[]) => syncRows('shots', PENDING_SHOTS_KEY, rows), [syncRows]);
  const syncPutts = useCallback((rows: Putt[]) => syncRows('putts', PENDING_PUTTS_KEY, rows), [syncRows]);

  const flushPendingImages = useCallback(async () => {
    if (!session?.user || !supabase) return;
    const scopedKey = `${PENDING_IMAGES_KEY}:${session.user.id}`;
    const pending = await readQueue<PendingImage>(scopedKey);
    for (const item of pending) {
      try {
        await syncShots([item.shot]);
        const { error: functionError } = await supabase.functions.invoke('shot-images', {
          body: { action: 'upload', shotId: item.shot.id, primaryBase64: item.primaryBase64, secondaryBase64: item.secondaryBase64 },
        });
        if (functionError) throw new Error(await functionErrorMessage(functionError));
        const remaining = (await readQueue<PendingImage>(scopedKey)).filter((queued) => queued.shot.id !== item.shot.id);
        if (remaining.length) await AsyncStorage.setItem(scopedKey, JSON.stringify(remaining));
        else await AsyncStorage.removeItem(scopedKey);
      } catch (caught) {
        setError(`Shot image upload failed: ${caught instanceof Error ? caught.message : 'Unknown error.'}`);
        throw caught;
      }
    }
  }, [session, syncShots]);

  const scheduleImageWork = useCallback((work: () => Promise<void>) => {
    const next = imageWork.current.then(work, work);
    imageWork.current = next.catch(() => {});
    return next;
  }, []);

  const uploadShotCapture = useCallback((shot: Shot, primaryBase64: string, secondaryBase64?: string) => {
    if (!session?.user) return Promise.resolve();
    return scheduleImageWork(async () => {
      try {
        const scopedKey = `${PENDING_IMAGES_KEY}:${session.user.id}`;
        const pending = await readQueue<PendingImage>(scopedKey);
        const next = [...pending.filter((item) => item.shot.id !== shot.id), { shot, primaryBase64, secondaryBase64 }];
        await AsyncStorage.setItem(scopedKey, JSON.stringify(next));
        await flushPendingImages();
      } catch (caught) {
        setError(`Shot image upload failed: ${caught instanceof Error ? caught.message : 'Unknown error.'}`);
        throw caught;
      }
    });
  }, [session, scheduleImageWork, flushPendingImages]);

  useEffect(() => {
    if (!session) return;
    void scheduleImageWork(flushPendingImages).catch(() => {});
  }, [session, scheduleImageWork, flushPendingImages]);

  useEffect(() => {
    if (!session || Platform.OS === 'web') return;
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') void scheduleImageWork(flushPendingImages).catch(() => {});
    });
    return () => subscription.remove();
  }, [session, scheduleImageWork, flushPendingImages]);

  const getShotImage = useCallback(async (shotId: string, camera: 'primary' | 'secondary' = 'primary') => {
    if (!session?.user || !supabase) throw new Error('Sign in to view shot images.');
    const { data, error: functionError } = await supabase.functions.invoke<{ mimeType: string; base64: string }>('shot-images', {
      body: { action: 'read', shotId, camera },
    });
    if (functionError) throw new Error(await functionErrorMessage(functionError));
    if (!data?.base64) throw new Error('Shot image was not returned.');
    return `data:${data.mimeType};base64,${data.base64}`;
  }, [session]);

  const repairShotImage = useCallback(async (shotId: string) => {
    if (!session?.user || !supabase) throw new Error('Sign in to repair shot images.');
    const { data, error: functionError } = await supabase.functions.invoke<{ imagePath: string | null; secondaryImagePath: string | null }>('shot-images', {
      body: { action: 'repair', shotId },
    });
    if (functionError) throw new Error(await functionErrorMessage(functionError));
    return { imagePath: data?.imagePath ?? null, secondaryImagePath: data?.secondaryImagePath ?? null };
  }, [session]);

  const beginFrameUpload = useCallback(async (shotId: string) => {
    if (!session?.user || !supabase) throw new Error('Sign in to upload capture frames.');
    const { data, error: functionError } = await supabase.functions.invoke<{ token: string; frameCount: number; expiresAt: string }>('shot-images', {
      body: { action: 'startFrameUpload', shotId },
    });
    if (functionError) throw new Error(await functionErrorMessage(functionError));
    if (!data?.token || !data.frameCount) throw new Error('Frame upload ticket was not returned.');
    return data;
  }, [session]);

  const getUploadedFrameIndices = useCallback(async (shotId: string) => {
    if (!session?.user || !supabase) throw new Error('Sign in to view capture frames.');
    const indices: number[] = [];
    for (let offset = 0; offset < 2000; offset += 1000) {
      const { data, error: dbError } = await supabase.from('shot_frames').select('frame_index')
        .eq('user_id', session.user.id).eq('shot_id', shotId).order('frame_index').range(offset, offset + 999);
      if (dbError) throw dbError;
      indices.push(...(data ?? []).map((frame) => frame.frame_index));
      if ((data ?? []).length < 1000) break;
    }
    return indices;
  }, [session]);

  const getCloudShotFrame = useCallback(async (shotId: string, frameIndex: number) => {
    if (!session?.user || !supabase) throw new Error('Sign in to view capture frames.');
    const { data, error: functionError } = await supabase.functions.invoke<CaptureFramePreview>('shot-images', {
      body: { action: 'readFrame', shotId, frameIndex },
    });
    if (functionError) throw new Error(await functionErrorMessage(functionError));
    if (!data?.base64) throw new Error('This frame has not been uploaded yet.');
    return data;
  }, [session]);

  const restoreRows = useCallback(async <T,>(table: 'shots' | 'putts'): Promise<T[]> => {
    if (!session?.user || !supabase) return [];
    const fetchRows = () => supabase!.from(table).select('*').eq('user_id', session.user.id).order('created_at', { ascending: false });
    let result = await fetchRows();
    if (result.error && /jwt|token/i.test(result.error.message)) {
      const refreshed = await supabase.auth.refreshSession();
      if (refreshed.error) {
        setError(`Cloud restore could not refresh the sign-in token: ${refreshed.error.message}`);
        throw refreshed.error;
      }
      result = await fetchRows();
    }
    if (result.error) {
      setError(`Cloud restore failed: ${result.error.message}`);
      throw result.error;
    }
    return (result.data ?? []).map((row) => {
      const record = row as { data: T; image_path?: string | null; secondary_image_path?: string | null };
      const value = record.data;
      if (table === 'shots') return {
        ...value,
        cloudImagePath: record.image_path ?? undefined,
        cloudSecondaryImagePath: record.secondary_image_path ?? undefined,
      } as T;
      return value;
    });
  }, [session]);
  const restoreShots = useCallback(async () => {
    const shots = await restoreRows<Shot>('shots');
    for (const shot of shots.filter((item) => item.captureId && !item.cloudImagePath).slice(0, 10)) {
      try {
        const paths = await repairShotImage(shot.id);
        if (paths.imagePath) shot.cloudImagePath = paths.imagePath;
        if (paths.secondaryImagePath) shot.cloudSecondaryImagePath = paths.secondaryImagePath;
      } catch (caught) {
        setError(`Shot image recovery failed: ${caught instanceof Error ? caught.message : 'Unknown error.'}`);
      }
    }
    return shots;
  }, [restoreRows, repairShotImage]);
  const restorePutts = useCallback(() => restoreRows<Putt>('putts'), [restoreRows]);

  const savePreference = useCallback(async (key: string, value: string) => {
    if (!session?.user || !supabase) return;
    const { error: dbError } = await supabase.from('preferences').upsert({
      user_id: session.user.id,
      key,
      value,
      updated_at: new Date().toISOString(),
    }, { onConflict: 'user_id,key' });
    if (dbError) { setError(`Cloud sync failed: ${dbError.message}`); throw dbError; }
  }, [session]);

  const restorePreferences = useCallback(async () => {
    if (!session?.user || !supabase) return {};
    const fetchPreferences = () => supabase!.from('preferences').select('key,value').eq('user_id', session.user.id);
    let result = await fetchPreferences();
    if (result.error && /jwt|token/i.test(result.error.message)) {
      const refreshed = await supabase.auth.refreshSession();
      if (refreshed.error) {
        setError(`Cloud restore could not refresh the sign-in token: ${refreshed.error.message}`);
        throw refreshed.error;
      }
      result = await fetchPreferences();
    }
    if (result.error) {
      setError(`Cloud restore failed: ${result.error.message}`);
      throw result.error;
    }
    return Object.fromEntries((result.data ?? []).map((item) => [item.key, item.value]));
  }, [session]);

  const value = useMemo(() => ({ configured: supabaseConfigured, session, authReady, busy, error, notice, signIn, signUp, signOut, resetPassword, syncShots, syncPutts, uploadShotCapture, repairShotImage, getShotImage, beginFrameUpload, getUploadedFrameIndices, getCloudShotFrame, restoreShots, restorePutts, savePreference, restorePreferences }),
    [session, authReady, busy, error, notice, signIn, signUp, signOut, resetPassword, syncShots, syncPutts, uploadShotCapture, repairShotImage, getShotImage, beginFrameUpload, getUploadedFrameIndices, getCloudShotFrame, restoreShots, restorePutts, savePreference, restorePreferences]);
  return <CloudSyncContext.Provider value={value}>{children}</CloudSyncContext.Provider>;
}

export function useCloudSync(): CloudSyncValue {
  const value = useContext(CloudSyncContext);
  if (!value) throw new Error('useCloudSync must be used inside CloudSyncProvider');
  return value;
}
