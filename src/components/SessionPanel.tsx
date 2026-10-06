import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useMemo, useState } from 'react';
import { Platform, Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';

import { SessionDraft, SessionEditor } from '@/components/SessionEditor';
import { Eyebrow, Surface } from '@/components/ui';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { useUnits } from '@/context/UnitsContext';
import { colors, radii, spacing } from '@/theme';
import { PracticeSession, Shot } from '@/types';
import { MPH_PER_MPS, YARDS_PER_METER } from '@/utils/referenceInput';
import { sessionCsv, sessionShots, sortSessions } from '@/utils/sessions';

/** "All shots", one session, or the shots hit outside any session. */
export type SessionView = { kind: 'all' } | { kind: 'none' } | { kind: 'session'; id: string };

function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return `${date.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

/**
 * Start, end, pick and export sessions. The picked view drives the statistics
 * below it on the Sessions screen.
 */
export function SessionPanel({
  shots, view, onChangeView,
}: {
  shots: Shot[];
  view: SessionView;
  onChangeView: (view: SessionView) => void;
}) {
  const { sessions, activeSession, startSession, endSession, resumeSession, updateSession, deleteSession } = useLaunchMonitor();
  const units = useUnits();
  // undefined: editor closed; null: starting a new session.
  const [editing, setEditing] = useState<PracticeSession | null | undefined>(undefined);
  const [exportNote, setExportNote] = useState<string | null>(null);
  const ordered = useMemo(() => sortSessions(sessions), [sessions]);
  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const shot of shots) if (shot.sessionId) map.set(shot.sessionId, (map.get(shot.sessionId) ?? 0) + 1);
    return map;
  }, [shots]);
  const unfiled = shots.filter((shot) => !shot.sessionId).length;
  const viewed = view.kind === 'session' ? sessions.find((item) => item.id === view.id) ?? null : null;
  const viewedShots = view.kind === 'all' ? shots : view.kind === 'none' ? sessionShots(shots, null) : sessionShots(shots, view.id);

  const save = (draft: SessionDraft) => {
    if (editing) {
      updateSession({
        ...editing,
        name: draft.name.trim() || editing.name,
        referenceDevice: draft.referenceDevice.trim() || undefined,
        notes: draft.notes.trim() || undefined,
      });
    } else {
      const created = startSession(draft);
      onChangeView({ kind: 'session', id: created.id });
    }
    setEditing(undefined);
  };

  const exportCsv = async () => {
    const csv = sessionCsv(viewed, viewedShots, {
      speedLabel: units.speedLabel.replace('/', ''),
      distanceLabel: units.distanceLabel,
      speed: (mps) => (units.speedUnit === 'mph' ? mps * MPH_PER_MPS : mps * 3.6),
      distance: (meters) => (units.distanceUnit === 'yd' ? meters * YARDS_PER_METER : meters),
    });
    const title = `${viewed?.name ?? (view.kind === 'none' ? 'Unfiled shots' : 'All shots')} - LM1.csv`;
    try {
      if (Platform.OS === 'web') {
        const clipboard = (globalThis as { navigator?: { clipboard?: { writeText(text: string): Promise<void> } } }).navigator?.clipboard;
        if (!clipboard) throw new Error('Clipboard is not available in this browser.');
        await clipboard.writeText(csv);
        setExportNote(`CSV for ${viewedShots.length} shots copied to the clipboard.`);
        return;
      }
      await Share.share({ message: csv, title }, { dialogTitle: title, subject: title });
      setExportNote(null);
    } catch (caught) {
      setExportNote(caught instanceof Error ? caught.message : 'Could not export the session.');
    }
  };

  return (
    <>
      <Surface style={styles.card}>
        <View style={styles.top}>
          <View style={styles.topCopy}>
            <Eyebrow>{activeSession ? 'Session open' : 'No open session'}</Eyebrow>
            <Text style={styles.title} numberOfLines={1}>{activeSession ? activeSession.name : 'Shots are not being filed'}</Text>
            <Text style={styles.meta}>
              {activeSession
                ? `Started ${formatWhen(activeSession.startedAt)} · ${counts.get(activeSession.id) ?? 0} shots${activeSession.referenceDevice ? ` · vs ${activeSession.referenceDevice}` : ''}`
                : 'Start one before hitting so every shot lands in the right place.'}
            </Text>
          </View>
          {activeSession ? (
            <Pressable accessibilityRole="button" onPress={endSession} style={({ pressed }) => [styles.secondary, pressed && styles.pressed]}>
              <Ionicons name="stop-circle-outline" size={16} color={colors.text} />
              <Text style={styles.secondaryText}>End</Text>
            </Pressable>
          ) : (
            <Pressable accessibilityRole="button" onPress={() => setEditing(null)} style={({ pressed }) => [styles.primary, pressed && styles.pressed]}>
              <Ionicons name="play" size={16} color={colors.accentInk} />
              <Text style={styles.primaryText}>Start</Text>
            </Pressable>
          )}
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
          <Chip label={`All · ${shots.length}`} active={view.kind === 'all'} onPress={() => onChangeView({ kind: 'all' })} />
          {ordered.map((session) => (
            <Chip
              key={session.id}
              label={`${session.name} · ${counts.get(session.id) ?? 0}`}
              active={view.kind === 'session' && view.id === session.id}
              open={!session.endedAt}
              onPress={() => onChangeView({ kind: 'session', id: session.id })}
            />
          ))}
          {unfiled ? <Chip label={`No session · ${unfiled}`} active={view.kind === 'none'} onPress={() => onChangeView({ kind: 'none' })} /> : null}
        </ScrollView>

        {viewed ? (
          <View style={styles.viewed}>
            <Text style={styles.viewedMeta}>
              {formatWhen(viewed.startedAt)}{viewed.endedAt ? ` → ${formatWhen(viewed.endedAt)}` : ' · open'}
              {viewed.referenceDevice ? ` · reference ${viewed.referenceDevice}` : ''}
            </Text>
            {viewed.notes ? <Text style={styles.viewedNotes}>{viewed.notes}</Text> : null}
            <View style={styles.actions}>
              {viewed.endedAt ? (
                <Action icon="play-outline" label="Resume" onPress={() => resumeSession(viewed.id)} />
              ) : null}
              <Action icon="create-outline" label="Edit" onPress={() => setEditing(viewed)} />
              <Action icon="share-outline" label="Export CSV" onPress={() => void exportCsv()} disabled={!viewedShots.length} />
            </View>
          </View>
        ) : (
          <View style={styles.actions}>
            <Action icon="share-outline" label="Export CSV" onPress={() => void exportCsv()} disabled={!viewedShots.length} />
          </View>
        )}
        {exportNote ? <Text style={styles.exportNote}>{exportNote}</Text> : null}
      </Surface>

      <SessionEditor
        session={editing ?? null}
        visible={editing !== undefined}
        onClose={() => setEditing(undefined)}
        onSave={save}
        onDelete={(sessionId) => {
          deleteSession(sessionId);
          setEditing(undefined);
          if (view.kind === 'session' && view.id === sessionId) onChangeView({ kind: 'all' });
        }}
      />
    </>
  );
}

function Chip({ label, active, open = false, onPress }: { label: string; active: boolean; open?: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      onPress={onPress}
      style={({ pressed }) => [styles.chip, active && styles.chipActive, pressed && styles.pressed]}
    >
      {open ? <View style={[styles.dot, active && styles.dotActive]} /> : null}
      <Text numberOfLines={1} style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    </Pressable>
  );
}

function Action({ icon, label, onPress, disabled = false }: { icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void; disabled?: boolean }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [styles.action, disabled && styles.actionDisabled, pressed && styles.pressed]}
    >
      <Ionicons name={icon} size={15} color={colors.accent} />
      <Text style={styles.actionText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.sm, padding: spacing.lg },
  top: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm, justifyContent: 'space-between' },
  topCopy: { flex: 1, minWidth: 0 },
  title: { color: colors.text, fontSize: 21, fontWeight: '700', letterSpacing: -0.5, marginTop: 3 },
  meta: { color: colors.textMuted, fontSize: 11, lineHeight: 16, marginTop: 3 },
  primary: { alignItems: 'center', backgroundColor: colors.accent, borderRadius: radii.pill, flexDirection: 'row', gap: 5, paddingHorizontal: 14, paddingVertical: 9 },
  primaryText: { color: colors.accentInk, fontSize: 13, fontWeight: '800' },
  secondary: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderColor: colors.lineStrong, borderRadius: radii.pill, borderWidth: 1, flexDirection: 'row', gap: 5, paddingHorizontal: 14, paddingVertical: 9 },
  secondaryText: { color: colors.text, fontSize: 13, fontWeight: '800' },
  chips: { gap: 6, paddingVertical: 2 },
  chip: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderColor: colors.line, borderRadius: radii.pill, borderWidth: 1, flexDirection: 'row', gap: 5, maxWidth: 220, paddingHorizontal: 12, paddingVertical: 7 },
  chipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipText: { color: colors.textMuted, fontSize: 11, fontWeight: '700' },
  chipTextActive: { color: colors.accentInk },
  dot: { backgroundColor: colors.accent, borderRadius: 3, height: 6, width: 6 },
  dotActive: { backgroundColor: colors.accentInk },
  viewed: { borderTopColor: colors.line, borderTopWidth: 1, gap: 4, paddingTop: spacing.sm },
  viewedMeta: { color: colors.textMuted, fontSize: 11 },
  viewedNotes: { color: colors.text, fontSize: 12, lineHeight: 17 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: 4 },
  action: { alignItems: 'center', flexDirection: 'row', gap: 4, paddingVertical: 4 },
  actionDisabled: { opacity: 0.4 },
  actionText: { color: colors.accent, fontSize: 12, fontWeight: '700' },
  exportNote: { color: colors.textMuted, fontSize: 11 },
  pressed: { opacity: 0.75 },
});
